from __future__ import division

__copyright__ = "Copyright (C) 2017 Dong Zhuang"

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

import six
import os
from datetime import datetime

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from unittest import skipIf

from relate.checks import register_startup_checks_extra

from tests.utils import mock
from tests.factories import UserFactory


class CheckRelateSettingsBase(SimpleTestCase):
    @property
    def func(self):
        from relate.checks import check_relate_settings
        return check_relate_settings

    @property
    def msg_id_prefix(self):
        raise NotImplementedError()

    def assertCheckMessages(self,  # noqa
                            expected_ids=None, expected_msgs=None, length=None,
                            filter_message_id_prefixes=None, ignore_order=False):
        """
        Check the run check result of the setting item of the testcase instance
        :param expected_ids: Optional, list of expected message id,
        default to None
        :param expected_msgs: Optional, list of expected message string,
        default to None
        :param length: Optional, length of expected check message,
        default to None
        :param filter_message_id_prefixes: a list or tuple of message id prefix,
        to restrict the
         run check result to be within the iterable.
        """
        if not filter_message_id_prefixes:
            filter_message_id_prefixes = self.msg_id_prefix
            if isinstance(filter_message_id_prefixes, str):
                filter_message_id_prefixes = [filter_message_id_prefixes]
            assert isinstance(filter_message_id_prefixes, (list, tuple))

        if expected_ids is None and expected_msgs is None and length is None:
            raise RuntimeError("At least one parameter should be specified "
                               "to make the assertion")

        result = self.func(None)

        def is_id_in_filter(id, filter):
            prefix = id.split(".")[0]
            return prefix in filter

        try:
            result_ids, result_msgs = (
                list(zip(*[(r.id, r.msg) for r in result
                      if is_id_in_filter(r.id, filter_message_id_prefixes)])))

            if expected_ids is not None:
                assert isinstance(expected_ids, (list, tuple))
                if ignore_order:
                    result_ids = tuple(sorted(list(result_ids)))
                    expected_ids = sorted(list(expected_ids))
                self.assertEqual(result_ids, tuple(expected_ids))

            if expected_msgs is not None:
                assert isinstance(expected_msgs, (list, tuple))
                if ignore_order:
                    result_msgs = tuple(sorted(list(result_msgs)))
                    expected_msgs = sorted(list(expected_msgs))
                self.assertEqual(result_msgs, tuple(expected_msgs))

            if length is not None:
                self.assertEqual(len(expected_ids), len(result_ids))
        except ValueError as e:
            if "values to unpack" in str(e):
                if expected_ids or expected_msgs or length:
                    self.fail("Check message unexpectedly found to be empty")
            else:
                raise


class CheckRelateURL(CheckRelateSettingsBase):
    msg_id_prefix = "relate_base_url"

    VALID_CONF = "example.com"
    INVALID_CONF_NONE = None
    INVALID_CONF_EMPTY_LIST = []
    INVALID_CONF_SPACES = "  "

    @override_settings(RELATE_BASE_URL=VALID_CONF)
    def test_valid_relate_base_url1(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_NONE)
    def test_invalid_relate_base_url_none(self):
        self.assertCheckMessages(["relate_base_url.E001"])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_EMPTY_LIST)
    def test_invalid_relate_base_url_empty_list(self):
        self.assertCheckMessages(["relate_base_url.E002"])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_SPACES)
    def test_invalid_relate_base_url_spaces(self):
        self.assertCheckMessages(["relate_base_url.E003"])


class CheckRelateUserProfileMaskMethod(CheckRelateSettingsBase):
    # This TestCase is not pure for check, but also make sure it returned
    # expected result
    allow_database_queries = True

    msg_id_prefix = "relate_user_profile_mask_method"

    def setUp(self):
        super(CheckRelateUserProfileMaskMethod, self).setUp()
        self.user = UserFactory.create(first_name="my_first", last_name="my_last")

        from accounts.utils import relate_user_method_settings
        relate_user_method_settings.__dict__ = {}

    def test_get_masked_profile_not_configured(self):
        with override_settings():
            del settings.RELATE_USER_PROFILE_MASK_METHOD
            self.assertCheckMessages([])

            # make sure it runs without issue
            self.assertIsNotNone(self.user.get_masked_profile())

    def test_get_masked_profile_valid_none(self):
        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=None):
            self.assertCheckMessages([])

            # make sure it runs without issue
            self.assertIsNotNone(self.user.get_masked_profile())

    def test_get_masked_profile_valid_method1(self):
        def custom_method(u):
            return "%s%s" % ("User", str(u.pk + 1))

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            self.assertCheckMessages([])
            self.assertEqual(self.user.get_masked_profile(),
                             custom_method(self.user))

    def test_get_masked_profile_valid_method2(self):
        def custom_method(user=None):
            if user is not None:
                return "%s%s" % ("User", str(user.pk + 1))
            else:
                return ""

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            self.assertCheckMessages([])
            self.assertEqual(self.user.get_masked_profile(),
                             custom_method(self.user))

    def test_get_masked_profile_valid_method_path(self):
        with override_settings(
                RELATE_USER_PROFILE_MASK_METHOD=(
                        "tests.resource"
                        ".my_custom_get_masked_profile_method_valid")):
            self.assertCheckMessages([])
            from tests.resource import (
                my_custom_get_masked_profile_method_valid as custom_method)
            self.assertEqual(self.user.get_masked_profile(),
                             custom_method(self.user))

    def test_get_masked_profile_param_invalid1(self):
        # the method has 0 args/kwargs
        def custom_method():
            return "profile"

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            self.assertCheckMessages(['relate_user_profile_mask_method.E003'])

    def test_get_masked_profile_param_invalid2(self):
        # the method has 2 args/kwargs
        def custom_method(u, v):
            return "%s%s" % ("User", str(u.pk + 1))

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            self.assertCheckMessages(['relate_user_profile_mask_method.E003'])

    def test_get_masked_profile_param_invalid3(self):
        # the method has 2 args/kwargs
        def custom_method(u, v=None):
            return "%s%s" % ("User", str(u.pk + 1))

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            self.assertCheckMessages(['relate_user_profile_mask_method.E003'])

    def test_get_masked_profile_invalid_path(self):
        with override_settings(RELATE_USER_PROFILE_MASK_METHOD="invalid path"):
            self.assertCheckMessages(['relate_user_profile_mask_method.E001'])

    def test_get_masked_profile_valid_path_not_callable(self):
        with override_settings(
                RELATE_USER_PROFILE_MASK_METHOD=(
                        "tests.resource"
                        ".my_custom_get_masked_profile_method_invalid_str")):
            self.assertCheckMessages(['relate_user_profile_mask_method.E002'])

    def test_passed_check_but_return_none(self):
        with override_settings(
                RELATE_USER_PROFILE_MASK_METHOD=(
                        "tests.resource"
                        ".my_custom_get_masked_profile_method_valid_but_return_none")):  # noqa
            self.assertCheckMessages([])
            from tests.resource import (
                my_custom_get_masked_profile_method_valid_but_return_none
                as custom_method)

            # test method can run
            custom_method(self.user)

            with self.assertRaises(RuntimeError):
                self.user.get_masked_profile()

    def test_passed_check_but_return_empty_string(self):
        with override_settings(
                RELATE_USER_PROFILE_MASK_METHOD=(
                        "tests.resource"
                        ".my_custom_get_masked_profile_method_valid_but_return_emtpy_string")):  # noqa
            self.assertCheckMessages([])
            from tests.resource import (
                my_custom_get_masked_profile_method_valid_but_return_emtpy_string
                as custom_method)

            # test method can run
            custom_method(self.user)

            with self.assertRaises(RuntimeError):
                self.user.get_masked_profile()


class CheckRelateUserFullNameFormatMethod(CheckRelateSettingsBase):
    # This TestCase is not pure for check, but also make sure it returned
    # expected result
    allow_database_queries = True

    msg_id_prefix = "relate_user_full_name_format_method"

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_get_full_name(self):
        def valid_method(first_name, last_name):
            return "%s %s" % (last_name, first_name)

        def invalid_method1(first_name):
            return first_name

        def invalid_method2(first_name, last_name):
            return None

        def invalid_method3(first_name, last_name):
            return " "

        def invalid_method4(first_name, last_name):
            return b"my_name"

        def invalid_method5(first_name, last_name):
            return "my_name"

        def invalid_method6(first_name, last_name):
            return Exception()

        default_user_dict = {"first_name": "first_name", "last_name": "last_name"}
        default_result = "first_name last_name"

        user_get_full_name_test_kwargs_list = (
            ({"id": 1,
              "custom_method": None,
              "user_dict": {},
              "default": '',
              "not_allow_blank": None,
              "force_verbose_blank": "(blank) (blank)"}),
            ({"id": 2,
              "custom_method": None,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result}),
            ({"id": 3,
              "custom_method": valid_method,
              "user_dict": default_user_dict,
              "default": "last_name first_name",
              "not_allow_blank": "last_name first_name",
              "force_verbose_blank": "last_name first_name"}),
            ({"id": 4,
              "custom_method": invalid_method1,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W003']}),
            ({"id": 5,
              "custom_method": invalid_method2,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W004']}),
            ({"id": 6,
              "custom_method": invalid_method3,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W004']}),
            ({"id": 7,
              "custom_method": invalid_method4,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W004']}),
            ({"id": 8,
              "custom_method": invalid_method5,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W005']}),
            ({"id": 9,
              "custom_method": invalid_method6,
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W004']}),
            ({"id": 10,
              "custom_method": "abcd",  # a string
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W001']}),
            ({"id": 11,
              "custom_method":
                  "tests.resource.my_customized_get_full_name_method",
              "user_dict": default_user_dict,
              "default": "First_Name Last_Name",
              "not_allow_blank": "First_Name Last_Name",
              "force_verbose_blank": "First_Name Last_Name"}),
            ({"id": 12,
              "custom_method":
                  "tests.resource.my_customized_get_full_name_method_invalid",
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W004']}),
            ({"id": 13,
              "custom_method":
                  "tests.resource.my_customized_get_full_name_method_invalid_str",
              "user_dict": default_user_dict,
              "default": default_result,
              "not_allow_blank": default_result,
              "force_verbose_blank": default_result,
              "check_messages": ['relate_user_full_name_format_method.W002']}),
            ({"id": 14,
              "custom_method":
                  "tests.resource.my_customized_get_full_name_method",
              "user_dict": {"first_name": "first_name"},
              "default": "First_Name",
              "not_allow_blank": None,
              "force_verbose_blank": "First_Name (Blank)"}),
        )

        # Ensure no duplicate entries in user_get_full_name_test_kwargs_list
        # to generate error info when subTests fail.
        ids = set([kwargs["id"] for kwargs in user_get_full_name_test_kwargs_list])
        assert len(ids) == len(user_get_full_name_test_kwargs_list)

        for kwargs in user_get_full_name_test_kwargs_list:
            # clear cached_property
            from accounts.utils import relate_user_method_settings
            relate_user_method_settings.__dict__ = {}
            with self.subTest(id=kwargs["id"]):
                with override_settings(
                        RELATE_USER_FULL_NAME_FORMAT_METHOD=kwargs[
                            "custom_method"]):
                    check_messages = kwargs.get("check_messages", [])
                    self.assertCheckMessages(check_messages)

                    user = UserFactory(**kwargs["user_dict"])
                    self.assertEqual(user.get_full_name(), kwargs["default"])
                    self.assertEqual(user.get_full_name(allow_blank=False),
                                     kwargs["not_allow_blank"])
                    self.assertEqual(user.get_full_name(force_verbose_blank=True),
                                     kwargs["force_verbose_blank"])


class CheckRelateEmailAppellationPriorityList(CheckRelateSettingsBase):
    msg_id_prefix = "relate_email_appellation_priority_list"

    VALID_CONF_NONE = None
    VALID_CONF = ["full_name"]
    INVALID_CONF_STR = "name1"
    INVALID_CONF = ["name1", "name2"]

    @override_settings(RELATE_EMAIL_APPELLATION_PRIORITY_LIST=VALID_CONF_NONE)
    def test_relate_email_appellation_priority_list_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_EMAIL_APPELLATION_PRIORITY_LIST=VALID_CONF)
    def test_relate_email_appellation_priority_list_valid(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_EMAIL_APPELLATION_PRIORITY_LIST=INVALID_CONF_STR)
    def test_relate_email_appellation_priority_list_invalid_str(self):
        self.assertCheckMessages(
            ["relate_email_appellation_priority_list.W001"])

    @override_settings(RELATE_EMAIL_APPELLATION_PRIORITY_LIST=INVALID_CONF)
    def test_relate_email_appellation_priority_list_invalid(self):
        self.assertCheckMessages(["relate_email_appellation_priority_list.W002"])

    @override_settings(RELATE_EMAIL_APPELLATION_PRIORITY_LIST=None,
                       RELATE_EMAIL_APPELATION_PRIORITY_LIST=VALID_CONF)
    def test_relate_email_appellation_priority_list_type_deprecated(self):
        self.assertCheckMessages(["relate_email_appellation_priority_list.W003"])

    @override_settings(RELATE_EMAIL_APPELATION_PRIORITY_LIST=None,
                       RELATE_EMAIL_APPELLATION_PRIORITY_LIST=None)
    def test_relate_email_appellation_priority_list_type_deprecated_none(self):
        self.assertCheckMessages([])


class CheckRelateEmailConnections(CheckRelateSettingsBase):
    msg_id_prefix = "email_connections"

    VALID_CONF_NONE = None
    VALID_CONF_EMPTY_DICT = {}
    VALID_CONF = {
        "robot": {
            'backend': 'django.core.mail.backends.console.EmailBackend',
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },
        "other": {}
    }
    INVALID_CONF_EMPTY_LIST = []
    INVALID_CONF_LIST = [VALID_CONF]
    INVALID_CONF_LIST_AS_ITEM_VALUE = {
        "robot": ['blah@blah.com'],
        "other": [],
        "yet_another": {}
    }
    INVALID_CONF_INVALID_BACKEND = {
        "robot": {
            'backend': 'an.invalid.emailBackend',  # invalid backend
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },
        "other": {}
    }

    @override_settings(EMAIL_CONNECTIONS=VALID_CONF_NONE)
    def test_valid_email_connections_none(self):
        self.assertCheckMessages([])

    @override_settings(EMAIL_CONNECTIONS=VALID_CONF_EMPTY_DICT)
    def test_valid_email_connections_emtpy_dict(self):
        self.assertCheckMessages([])

    @override_settings(EMAIL_CONNECTIONS=VALID_CONF)
    def test_valid_email_connections(self):
        self.assertCheckMessages([])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_EMPTY_LIST)
    def test_invalid_email_connections_empty_list(self):
        self.assertCheckMessages(["email_connections.E001"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_LIST)
    def test_invalid_email_connections_list(self):
        self.assertCheckMessages(["email_connections.E001"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_LIST_AS_ITEM_VALUE)
    def test_invalid_email_connections_list_as_item_value(self):
        self.assertCheckMessages(
            ["email_connections.E002", "email_connections.E002"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_INVALID_BACKEND)
    def test_invalid_email_connections_invalid_backend(self):
        self.assertCheckMessages(["email_connections.E003"])


class CheckRelateFacilities(CheckRelateSettingsBase):
    msg_id_prefix = "relate_facilities"

    VALID_CONF_NONE = None
    VALID_CONF = (
        {
            "test_center": {
                "ip_ranges": ["192.168.192.0/24"],
                "exams_only": False},
            "test_center2": {
                "ip_ranges": ["192.168.10.0/24"]},
        })

    INVALID_CONF_LIST = []
    INVALID_CONF_NOT_DICT_AS_ITEM_VALUE = (
        {
            "test_center": {
                "ip_ranges": ["192.168.192.0/24"],
                "exams_only": False},
            "test_center2": [],  # not a dict
            "test_center3": ("192.168.10.0/24"),  # not a dict
        })

    INVALID_CONF_IP_RANGES_NOT_LIST = (
        {
            "test_center": {
                "ip_ranges": "192.168.192.0/24",  # not a list
                "exams_only": False},
            "test_center2": [],
        })

    INVALID_CONF_IP_RANGES_ITEM_NOT_IPADDRESS = (
        {
            "test_center": {
                "ip_ranges": ["www.example.com", "localhost"]  # invalid ipadd
            },
        })

    WARNING_CONF_IP_RANGES_NOT_CONFIGURED = (
        {
            "test_center": {"exams_only": False},
            "test_center2": {},
        })

    @override_settings(RELATE_FACILITIES=VALID_CONF_NONE)
    def test_valid_relate_facilities_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_FACILITIES=VALID_CONF)
    def test_valid_relate_facilities(self):
        self.assertCheckMessages([])

    def test_valid_relate_facilities_callable(self):
        def valid_func(now_datetime):
            from django.utils.timezone import now
            if now_datetime > now():
                return self.VALID_CONF
            else:
                return {}

        with override_settings(RELATE_FACILITIES=valid_func):
            self.assertCheckMessages([])

    def test_valid_relate_facilities_callable_with_empty_ip_ranges(self):
        def valid_func_though_return_emtpy_ip_ranges(now_datetime):
            # this won't result in warnning, because the facility is defined
            # by a callable.
            return self.WARNING_CONF_IP_RANGES_NOT_CONFIGURED
        with override_settings(
                RELATE_FACILITIES=valid_func_though_return_emtpy_ip_ranges):
            self.assertCheckMessages([])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_LIST)
    def test_invalid_relate_facilities_callable_return_list(self):
        self.assertCheckMessages(["relate_facilities.E002"])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_NOT_DICT_AS_ITEM_VALUE)
    def test_invalid_relate_facilities_callable_not_dict_as_item_value(self):
        self.assertCheckMessages(
            ["relate_facilities.E003", "relate_facilities.E003"])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_IP_RANGES_NOT_LIST)
    def test_invalid_relate_facilities_ip_ranges_not_list(self):
        self.assertCheckMessages(
            ["relate_facilities.E003", "relate_facilities.E004"],
            ignore_order=True)

    @override_settings(RELATE_FACILITIES=INVALID_CONF_IP_RANGES_ITEM_NOT_IPADDRESS)
    def test_invalid_relate_facilities_ip_ranges_item_not_ipaddress(self):
        self.assertCheckMessages(
            ["relate_facilities.E005", "relate_facilities.E005"],
            ignore_order=True)

    def test_invalid_relate_facilities_callable_not_return_dict(self):
        def invalid_func_not_return_dict(now_datetime):
            return self.INVALID_CONF_LIST

        with override_settings(RELATE_FACILITIES=invalid_func_not_return_dict):
            self.assertCheckMessages(["relate_facilities.E001"])

    def test_invalid_relate_facilities_callable_return_invalid_conf(self):
        def invalid_func_return_invalid_conf(now_datetime):
            return self.INVALID_CONF_NOT_DICT_AS_ITEM_VALUE

        with override_settings(RELATE_FACILITIES=invalid_func_return_invalid_conf):
            self.assertCheckMessages(
                ["relate_facilities.E003", "relate_facilities.E003"])

    def test_invalid_relate_facilities_callable_return_none(self):
        def invalid_func_return_none(now_datetime):
            return None

        with override_settings(RELATE_FACILITIES=invalid_func_return_none):
            self.assertCheckMessages(["relate_facilities.E001"])

    @override_settings(RELATE_FACILITIES=WARNING_CONF_IP_RANGES_NOT_CONFIGURED)
    def test_warning_relate_facilities(self):
        self.assertCheckMessages(
            ["relate_facilities.W001", "relate_facilities.W001"])


class CheckRelateMaintenanceModeExceptions(CheckRelateSettingsBase):
    msg_id_prefix = "relate_maintenance_mode_exceptions"

    VALID_CONF_NONE = None
    VALID_CONF_EMPTY_LIST = []
    VALID_CONF = ["127.0.0.1", "192.168.1.1"]
    INVALID_CONF_STR = "127.0.0.1"
    INVALID_CONF_DICT = {"localhost": "127.0.0.1",
                     "www.myrelate.com": "192.168.1.1"}
    INVALID_CONF_INVALID_IPS = ["localhost", "www.myrelate.com"]

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF_NONE)
    def test_valid_maintenance_mode_exceptions_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF_EMPTY_LIST)
    def test_valid_maintenance_mode_exceptions_emtpy_list(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF)
    def test_valid_maintenance_mode_exceptions(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_STR)
    def test_invalid_maintenance_mode_exceptions_str(self):
        self.assertCheckMessages(["relate_maintenance_mode_exceptions.E001"])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_DICT)
    def test_invalid_maintenance_mode_exceptions_dict(self):
        self.assertCheckMessages(["relate_maintenance_mode_exceptions.E001"])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_INVALID_IPS)
    def test_invalid_maintenance_mode_exceptions_invalid_ipaddress(self):
        self.assertCheckMessages(["relate_maintenance_mode_exceptions.E002",
                                  "relate_maintenance_mode_exceptions.E002"])


class CheckRelateSessionRestartCooldownSeconds(CheckRelateSettingsBase):
    msg_id_prefix = "relate_session_restart_cooldown_seconds"

    VALID_CONF = 10
    VALID_CONF_BY_CALC = 2 * 5
    INVALID_CONF_STR = "10"
    INVALID_CONF_LIST = [10]
    INVALID_CONF_NEGATIVE = -10

    @override_settings()
    def test_valid_relate_session_restart_cooldown_seconds_not_configured(self):
        del settings.RELATE_SESSION_RESTART_COOLDOWN_SECONDS
        self.assertCheckMessages([])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=None)
    def test_valid_relate_session_restart_cooldown_seconds_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=VALID_CONF)
    def test_valid_relate_session_restart_cooldown_seconds(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=VALID_CONF_BY_CALC)
    def test_valid_relate_session_restart_cooldown_seconds_by_calc(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_STR)
    def test_invalid_maintenance_mode_exceptions_str(self):
        self.assertCheckMessages(
            ["relate_session_restart_cooldown_seconds.E001"])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_LIST)
    def test_invalid_maintenance_mode_exceptions_list(self):
        self.assertCheckMessages(
            ["relate_session_restart_cooldown_seconds.E001"])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_NEGATIVE)
    def test_invalid_maintenance_mode_exceptions_list_negative(self):
        self.assertCheckMessages(
            ["relate_session_restart_cooldown_seconds.E002"])


class CheckRelateTicketMinutesValidAfterUse(CheckRelateSettingsBase):
    msg_id_prefix = "relate_ticket_minutes_valid_after_use"

    VALID_CONF = 10
    VALID_CONF_BY_CALC = 2 * 5
    INVALID_CONF_STR = "10"
    INVALID_CONF_LIST = [10]
    INVALID_CONF_NEGATIVE = -10

    @override_settings()
    def test_valid_relate_ticket_not_configured(self):
        del settings.RELATE_TICKET_MINUTES_VALID_AFTER_USE
        self.assertCheckMessages([])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=None)
    def test_valid_relate_ticket_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=VALID_CONF)
    def test_valid_relate_ticket_minutes_valid_after_use(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=VALID_CONF_BY_CALC)
    def test_valid_relate_ticket_minutes_valid_after_use_by_calc(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_STR)
    def test_invalid_relate_ticket_minutes_valid_after_use_str(self):
        self.assertCheckMessages(
            ["relate_ticket_minutes_valid_after_use.E001"])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_LIST)
    def test_invalid_relate_ticket_minutes_valid_after_use_list(self):
        self.assertCheckMessages(
            ["relate_ticket_minutes_valid_after_use.E001"])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_NEGATIVE)
    def test_invalid_relate_ticket_minutes_valid_after_use_negative(self):
        self.assertCheckMessages(
            ["relate_ticket_minutes_valid_after_use.E002"])


def side_effect_os_path_is_dir(*args, **kwargs):
    if args[0].startswith("dir"):
        return True
    return False


def side_effect_os_access(*args, **kwargs):
    if args[0].endswith("NEITHER"):
        return False
    elif args[0].endswith("W_FAIL"):
        if args[1] == os.W_OK:
            return False
    elif args[0].endswith("R_FAIL"):
        if args[1] == os.R_OK:
            return False
    return True


@mock.patch('os.access', side_effect=side_effect_os_access)
@mock.patch("os.path.isdir", side_effect=side_effect_os_path_is_dir)
class CheckGitRoot(CheckRelateSettingsBase):
    msg_id_prefix = "git_root"

    VALID_GIT_ROOT = "dir/git/root/path"
    INVALID_GIT_ROOT_NONE = None
    INVALID_GIT_ROOT_LIST = [VALID_GIT_ROOT]
    INVALID_GIT_ROOT_SPACES = " "
    INVALID_GIT_ROOT_NOT_DIR = "not_dir/git/root/path"
    INVALID_GIT_ROOT_W_FAIL = "dir/git/root/path/W_FAIL"
    INVALID_GIT_ROOT_R_FAIL = "dir/git/root/path/R_FAIL"
    INVALID_GIT_ROOT_W_R_FAIL = "dir/git/root/path/NEITHER"

    @override_settings(GIT_ROOT=VALID_GIT_ROOT)
    def test_valid_git_root(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertCheckMessages([])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_NONE)
    def test_invalid_git_root_none(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertCheckMessages(["git_root.E001"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_LIST)
    def test_invalid_git_root_list(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertCheckMessages(["git_root.E002"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_SPACES)
    def test_invalid_git_root_spaces(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertCheckMessages(["git_root.E003"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_NOT_DIR)
    def test_invalid_git_root(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertCheckMessages(["git_root.E003"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_W_FAIL)
    def test_invalid_git_root_no_write_perm(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no write permission
        self.assertCheckMessages(["git_root.E004"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_R_FAIL)
    def test_invalid_git_root_no_read_perms(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no read permission
        self.assertCheckMessages(["git_root.E005"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_W_R_FAIL)
    def test_invalid_git_root_no_both_perms(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no write and read permissions
        self.assertCheckMessages(["git_root.E004", "git_root.E005"])


class CheckRelateCourseLanguages(CheckRelateSettingsBase):
    """
    For this tests to pass, LANGUAGE_CODE, LANGUAGES, USE_I18N in
    local_settings_example.py should not be configured"""

    msg_id_prefix = "relate_languages"

    VALID_CONF1 = [
        ('en', _('my English')),
        ('zh-hans', _('Simplified Chinese')),
        ('de', _('German'))]
    VALID_CONF2 = (
        ('en', _('English')),
        ('zh-hans', _('Simplified Chinese')),
        ('de', _('German')))
    VALID_CONF3 = (
        ('en', 'English'),
        ('zh-hans', 'Simplified Chinese'),
        ('de', _('German')))

    VALID_WITH_WARNNING_CONF = (
        ('en', 'English'),
        ('zh-hans', 'Simplified Chinese'),
        ('zh-hans', 'my Simplified Chinese'),
        ('de', _('German')))

    VALID_CONF4 = [('en', ('English',)), ]
    VALID_CONF5 = (['en', 'English'],)
    VALID_CONF6 = [(('en',), _('English')), ]

    INVALID_CONF1 = {
        'en': 'English',
        'zh-hans': 'Simplified Chinese',
        'de': _('German')}
    INVALID_CONF2 = (('en',),)
    INVALID_CONF3 = [('en',), ([], 'English'), ["1", "2"]]
    INVALID_CONF4 = "some thing"

    def test_valid(self):
        with override_settings(LANGUAGES=self.VALID_CONF1):
            self.assertCheckMessages([])

        with override_settings(LANGUAGES=self.VALID_CONF2):
            self.assertCheckMessages([])

        with override_settings(LANGUAGES=self.VALID_CONF3):
            self.assertCheckMessages([])

        with override_settings(LANGUAGES=self.VALID_CONF4):
            self.assertCheckMessages([])

        with override_settings(LANGUAGES=self.VALID_CONF5):
            self.assertCheckMessages([])

        with override_settings(LANGUAGES=self.VALID_CONF6):
            self.assertCheckMessages([])

    def test_lang_not_list_or_tuple(self):
        with override_settings(LANGUAGES=self.INVALID_CONF1):
            self.assertCheckMessages(["relate_languages.E002"])

    def test_lang_item_not_2_tuple(self):
        with override_settings(LANGUAGES=self.INVALID_CONF2):
            self.assertCheckMessages(["relate_languages.E002"])

    def test_lang_multiple_error(self):
        with override_settings(LANGUAGES=self.INVALID_CONF3):
            self.assertCheckMessages(["relate_languages.E002"])

    def test_lang_type_string(self):
        with override_settings(LANGUAGES=self.INVALID_CONF4):
            self.assertCheckMessages(["relate_languages.E001"])

    def test_item_having_same_lang_code_with_settings_language_code(self):
        with override_settings(LANGUAGES=self.VALID_CONF1, LANGUAGE_CODE="en"):
            # This should not generate warning of duplicate language entries
            # since that is how Django works.
            self.assertCheckMessages([])

    def test_item_duplicated_inside_settings_languages(self):
        with override_settings(LANGUAGES=self.VALID_WITH_WARNNING_CONF,
                               LANGUAGE_CODE="en-us"):
            self.assertCheckMessages(
                expected_ids=["relate_languages.W001"],

                # 'my Simplified Chinese' is used for language description of
                # 'zh-hans' instead of 'Simplified Chinese'
                expected_msgs=[
                    "Duplicate language entries were found in "
                    "settings.LANGUAGES for 'zh-hans', 'my Simplified "
                    "Chinese' will be used as its "
                    "language_description"]
            )


class CheckRelateSiteName(CheckRelateSettingsBase):
    msg_id_prefix = "relate_site_name"

    VALID_CONF = "My RELATE"
    INVALID_CONF = ["My RELATE"]

    def test_site_name_not_configured(self):
        with override_settings():
            del settings.RELATE_SITE_NAME
            self.assertCheckMessages(["relate_site_name.E001"])

    def test_site_name_none(self):
        with override_settings(RELATE_SITE_NAME=None):
            self.assertCheckMessages(["relate_site_name.E002"])

    def test_site_name_invalid_instance_error(self):
        with override_settings(RELATE_SITE_NAME=self.INVALID_CONF):
            self.assertCheckMessages(["relate_site_name.E003"])

    def test_site_name_blank_string(self):
        with override_settings(RELATE_SITE_NAME="  "):
            self.assertCheckMessages(["relate_site_name.E004"])


TEST_MY_OVERRIDING_TEMPLATES_DIR = "/path/to/my_template/"


def is_dir_side_effect(*args, **kwargs):
    if TEST_MY_OVERRIDING_TEMPLATES_DIR in args:
        return True
    else:
        return False


class CheckRelateTemplatesDirs(CheckRelateSettingsBase):
    msg_id_prefix = "relate_override_templates_dirs"

    VALID_CONF = [TEST_MY_OVERRIDING_TEMPLATES_DIR]
    INVALID_CONF1 = TEST_MY_OVERRIDING_TEMPLATES_DIR  # string
    INVALID_CONF2 = [(TEST_MY_OVERRIDING_TEMPLATES_DIR,)]  # items not string
    INVALID_CONF3 = [TEST_MY_OVERRIDING_TEMPLATES_DIR,
                     "some/where/does/not/exist",
                     "yet/another/invalid/path"]

    def test_valid_conf(self):
        with override_settings(RELATE_OVERRIDE_TEMPLATES_DIRS=self.VALID_CONF):
            with mock.patch("relate.checks.os.path.isdir",
                            side_effect=is_dir_side_effect):
                self.assertCheckMessages([])

    def test_not_configured(self):
        with override_settings():
            del settings.RELATE_OVERRIDE_TEMPLATES_DIRS
            self.assertCheckMessages([])

    def test_configured_none(self):
        with override_settings(RELATE_OVERRIDE_TEMPLATES_DIRS=None):
            self.assertCheckMessages([])

    def test_invalid_instance_error(self):
        with override_settings(RELATE_OVERRIDE_TEMPLATES_DIRS=self.INVALID_CONF1):
            self.assertCheckMessages(["relate_override_templates_dirs.E001"])

    def test_invalid_item_instance_error(self):
        with override_settings(RELATE_OVERRIDE_TEMPLATES_DIRS=self.INVALID_CONF2):
            self.assertCheckMessages(["relate_override_templates_dirs.E002"])

    def test_invalid_path(self):
        with override_settings(RELATE_OVERRIDE_TEMPLATES_DIRS=self.INVALID_CONF3):
            with mock.patch("relate.checks.os.path.isdir",
                            side_effect=is_dir_side_effect):
                self.assertCheckMessages(
                    ["relate_override_templates_dirs.W001",
                     "relate_override_templates_dirs.W001"])


class CheckRelateCustomPageTypesRemovedDeadline(CheckRelateSettingsBase):
    msg_id_prefix = "relate_custom_page_types_removed_deadline"
    VALID_CONF = datetime(2017, 12, 31, 0, 0)
    INVALID_CONF = "2017-12-31 00:00"

    @override_settings(RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=None)
    def test_valid_conf_none(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=VALID_CONF)
    def test_valid_conf(self):
        self.assertCheckMessages([])

    @override_settings(RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=INVALID_CONF)
    def test_invalid_conf(self):
        self.assertCheckMessages(
            ["relate_custom_page_types_removed_deadline.E001"])


class CheckRelateDisableCodehiliteMarkdownExtensions(CheckRelateSettingsBase):
    msg_id_prefix = "relate_disable_codehilite_markdown_extension"
    VALID_CONF = None
    VALID_CONF_NO_WARNING = True

    WARNING_CONF_NOT_BOOL1 = "some string"
    WARNING_CONF_NOT_BOOL2 = ["markdown.extensions.codehilite"]
    WARNING_CONF_FALSE = False

    @override_settings(RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=VALID_CONF)
    def test_valid_conf(self):
        self.assertCheckMessages([])

    @override_settings(
        RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=VALID_CONF_NO_WARNING)
    def test_valid_conf_no_warning(self):
        self.assertCheckMessages([])

    @override_settings(
        RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=WARNING_CONF_NOT_BOOL1)
    def test_warning_conf_not_bool1(self):
        self.assertCheckMessages(
            ["relate_disable_codehilite_markdown_extension.W001"])

    @override_settings(
        RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=WARNING_CONF_NOT_BOOL2)
    def test_warning_conf_not_bool2(self):
        self.assertCheckMessages(
            ["relate_disable_codehilite_markdown_extension.W001"])

    @override_settings(
        RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=WARNING_CONF_FALSE)
    def test_warning_conf_false(self):
        self.assertCheckMessages(
            ["relate_disable_codehilite_markdown_extension.W002"])


class RelateStartupChecksExtraCheckTest(CheckRelateSettingsBase):
    msg_id_prefix = "my_custom_check_msg"

    INSTANCE_WRONG1 = "tests.resouce.my_check_func"
    INSTANCE_WRONG2 = {"path": "tests.resouce.my_check_func"}

    @override_settings()
    def test_not_configured(self):
        del settings.RELATE_STARTUP_CHECKS_EXTRA
        register_startup_checks_extra()

    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=None)
    def test_none(self):
        register_startup_checks_extra()

    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=INSTANCE_WRONG1)
    def test_instance_error1(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            register_startup_checks_extra()

        expected_error_msg = (
            "RELATE_STARTUP_CHECKS_EXTRA must be an instance of list or tuple")
        self.assertIn(expected_error_msg, str(cm.exception))

    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=INSTANCE_WRONG2)
    def test_instance_error2(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            register_startup_checks_extra()

        expected_error_msg = (
            "RELATE_STARTUP_CHECKS_EXTRA must be an instance of list or tuple")
        self.assertIn(expected_error_msg, str(cm.exception))

    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=[])
    def test_empty_list(self):
        register_startup_checks_extra()

    @skipIf(six.PY2, "python 2 generate different message for ImportError")
    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=[
        "unknown_package.unknown_module.func"])
    def test_not_importable_check_func(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            register_startup_checks_extra()
        expected_error_msg = ("No module named 'unknown_package'")
        self.assertIn(expected_error_msg, str(cm.exception))

    @override_settings(RELATE_STARTUP_CHECKS_EXTRA=[
        "tests.resource.my_custom_check_func1",
        "tests.resource.my_custom_check_func2"])
    def test_do_check(self):
        from tests.utils import mock
        with mock.patch("relate.checks.register") as mock_register:
            register_startup_checks_extra()
            self.assertEqual(mock_register.call_count, 2)
            stringified_call_args = ". ".join(
                [repr(call) for call in mock_register.call_args_list])
            self.assertIn(
                "function my_custom_check_func1", stringified_call_args)
            self.assertIn(
                "function my_custom_check_func2", stringified_call_args)
