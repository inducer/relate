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

import os
from django.test import SimpleTestCase
from django.test.utils import override_settings
try:
    from unittest import mock
except Exception:
    import mock


class CheckRelateSettingsBase(SimpleTestCase):
    @property
    def func(self):
        from relate.checks import check_relate_settings
        return check_relate_settings


class CheckRelateURL(CheckRelateSettingsBase):
    VALID_CONF = "example.com"
    INVALID_CONF_NONE = None
    INVALID_CONF_EMPTY_LIST = []
    INVALID_CONF_SPACES = "  "

    @override_settings(RELATE_BASE_URL=VALID_CONF)
    def test_valid_relate_base_url1(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_NONE)
    def test_invalid_relate_base_url_none(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result], ["relate_base_url.E001"])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_EMPTY_LIST)
    def test_invalid_relate_base_url_empty_list(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result], ["relate_base_url.E002"])

    @override_settings(RELATE_BASE_URL=INVALID_CONF_SPACES)
    def test_invalid_relate_base_url_spaces(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result], ["relate_base_url.E003"])


class CheckRelateEmailAppelationPriorityList(CheckRelateSettingsBase):
    VALID_CONF_NONE = None
    VALID_CONF = ["name1", "name2"]
    INVALID_CONF_STR = "name1"

    @override_settings(RELATE_EMAIL_APPELATION_PRIORITY_LIST=VALID_CONF_NONE)
    def test_valid_relate_email_appelation_priority_list_none(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_EMAIL_APPELATION_PRIORITY_LIST=VALID_CONF)
    def test_valid_relate_email_appelation_priority_list(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_EMAIL_APPELATION_PRIORITY_LIST=INVALID_CONF_STR)
    def test_invalid_relate_email_appelation_priority_list_str(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_email_appelation_priority_list.E002"])


class CheckRelateEmailConnections(CheckRelateSettingsBase):
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
        self.assertEqual(self.func(None), [])

    @override_settings(EMAIL_CONNECTIONS=VALID_CONF_EMPTY_DICT)
    def test_valid_email_connections_emtpy_dict(self):
        self.assertEqual(self.func(None), [])

    @override_settings(EMAIL_CONNECTIONS=VALID_CONF)
    def test_valid_email_connections(self):
        self.assertEqual(self.func(None), [])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_EMPTY_LIST)
    def test_invalid_email_connections_empty_list(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["email_connections.E001"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_LIST)
    def test_invalid_email_connections_list(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["email_connections.E001"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_LIST_AS_ITEM_VALUE)
    def test_invalid_email_connections_list_as_item_value(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual([r.id for r in result],
                         ["email_connections.E002",
                          "email_connections.E002"])

    @override_settings(EMAIL_CONNECTIONS=INVALID_CONF_INVALID_BACKEND)
    def test_invalid_email_connections_invalid_backend(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["email_connections.E003"])


class CheckRelateFacilities(CheckRelateSettingsBase):
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
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_FACILITIES=VALID_CONF)
    def test_valid_relate_facilities(self):
        self.assertEqual(self.func(None), [])

    def test_valid_relate_facilities_callable(self):
        def valid_func(now_datetime):
            from django.utils.timezone import now
            if now_datetime > now():
                return self.VALID_CONF
            else:
                return {}

        with override_settings(RELATE_FACILITIES=valid_func):
            self.assertEqual(self.func(None), [])

    def test_valid_relate_facilities_callable_with_empty_ip_ranges(self):
        def valid_func_though_return_emtpy_ip_ranges(now_datetime):
            # this won't result in warnning, because the facility is defined
            # by a callable.
            return self.WARNING_CONF_IP_RANGES_NOT_CONFIGURED
        with override_settings(
                RELATE_FACILITIES=valid_func_though_return_emtpy_ip_ranges):
            self.assertEqual(self.func(None), [])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_LIST)
    def test_invalid_relate_facilities_callable_return_list(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_facilities.E002"])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_NOT_DICT_AS_ITEM_VALUE)
    def test_invalid_relate_facilities_callable_not_dict_as_item_value(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual([r.id for r in result],
                         ["relate_facilities.E003",
                          "relate_facilities.E003"])

    @override_settings(RELATE_FACILITIES=INVALID_CONF_IP_RANGES_NOT_LIST)
    def test_invalid_relate_facilities_ip_ranges_not_list(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted([r.id for r in result]),
                         sorted(["relate_facilities.E003",
                                 "relate_facilities.E004"]))

    @override_settings(RELATE_FACILITIES=INVALID_CONF_IP_RANGES_ITEM_NOT_IPADDRESS)
    def test_invalid_relate_facilities_ip_ranges_item_not_ipaddress(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted([r.id for r in result]),
                         sorted(["relate_facilities.E005",
                                 "relate_facilities.E005"]))

    def test_invalid_relate_facilities_callable_not_return_dict(self):
        def invalid_func_not_return_dict(now_datetime):
            return self.INVALID_CONF_LIST

        with override_settings(RELATE_FACILITIES=invalid_func_not_return_dict):
            self.assertEqual([r.id for r in self.func(None)],
                             ["relate_facilities.E001"])

    def test_invalid_relate_facilities_callable_return_invalid_conf(self):
        def invalid_func_return_invalid_conf(now_datetime):
            return self.INVALID_CONF_NOT_DICT_AS_ITEM_VALUE

        with override_settings(RELATE_FACILITIES=invalid_func_return_invalid_conf):
            result = self.func(None)
            self.assertEqual(len(result), 2)
            self.assertEqual([r.id for r in result],
                             ["relate_facilities.E003",
                              "relate_facilities.E003"])

    def test_invalid_relate_facilities_callable_return_none(self):
        def invalid_func_return_none(now_datetime):
            return None

        with override_settings(RELATE_FACILITIES=invalid_func_return_none):
            self.assertEqual([r.id for r in self.func(None)],
                             ["relate_facilities.E001"])

    @override_settings(RELATE_FACILITIES=WARNING_CONF_IP_RANGES_NOT_CONFIGURED)
    def test_warning_relate_facilities(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual([r.id for r in result],
                         ["relate_facilities.W001",
                          "relate_facilities.W001"])


class CheckRelateMaintenanceModeExceptions(CheckRelateSettingsBase):
    VALID_CONF_NONE = None
    VALID_CONF_EMPTY_LIST = []
    VALID_CONF = ["127.0.0.1", "192.168.1.1"]
    INVALID_CONF_STR = "127.0.0.1"
    INVALID_CONF_DICT = {"localhost": "127.0.0.1",
                     "www.myrelate.com": "192.168.1.1"}
    INVALID_CONF_INVALID_IPS = ["localhost", "www.myrelate.com"]

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF_NONE)
    def test_valid_maintenance_mode_exceptions_none(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF_EMPTY_LIST)
    def test_valid_maintenance_mode_exceptions_emtpy_list(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=VALID_CONF)
    def test_valid_maintenance_mode_exceptions(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_STR)
    def test_invalid_maintenance_mode_exceptions_str(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_maintenance_mode_exceptions.E001"])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_DICT)
    def test_invalid_maintenance_mode_exceptions_dict(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_maintenance_mode_exceptions.E001"])

    @override_settings(RELATE_MAINTENANCE_MODE_EXCEPTIONS=INVALID_CONF_INVALID_IPS)
    def test_invalid_maintenance_mode_exceptions_invalid_ipaddress(self):
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual([r.id for r in result],
                         ["relate_maintenance_mode_exceptions.E002",
                          "relate_maintenance_mode_exceptions.E002"])


class CheckRelateSessionRestartCooldownSeconds(CheckRelateSettingsBase):
    VALID_CONF = 10
    VALID_CONF_BY_CALC = 2 * 5
    INVALID_CONF_STR = "10"
    INVALID_CONF_LIST = [10]
    INVALID_CONF_NEGATIVE = -10

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=VALID_CONF)
    def test_valid_relate_session_restart_cooldown_seconds(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=VALID_CONF_BY_CALC)
    def test_valid_relate_session_restart_cooldown_seconds_by_calc(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_STR)
    def test_invalid_maintenance_mode_exceptions_str(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_session_restart_cooldown_seconds.E001"])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_LIST)
    def test_invalid_maintenance_mode_exceptions_list(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_session_restart_cooldown_seconds.E001"])

    @override_settings(RELATE_SESSION_RESTART_COOLDOWN_SECONDS=INVALID_CONF_NEGATIVE)
    def test_invalid_maintenance_mode_exceptions_list_negative(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_session_restart_cooldown_seconds.E002"])


class CheckRelateTicketMinutesValidAfterUse(CheckRelateSettingsBase):
    VALID_CONF = 10
    VALID_CONF_BY_CALC = 2 * 5
    INVALID_CONF_STR = "10"
    INVALID_CONF_LIST = [10]
    INVALID_CONF_NEGATIVE = -10

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=VALID_CONF)
    def test_valid_relate_ticket_minutes_valid_after_use(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=VALID_CONF_BY_CALC)
    def test_valid_relate_ticket_minutes_valid_after_use_by_calc(self):
        self.assertEqual(self.func(None), [])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_STR)
    def test_invalid_relate_ticket_minutes_valid_after_use_str(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_ticket_minutes_valid_after_use.E001"])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_LIST)
    def test_invalid_relate_ticket_minutes_valid_after_use_list(self):
        self.assertEqual([r.id for r in self.func(None)],
                         ["relate_ticket_minutes_valid_after_use.E001"])

    @override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=INVALID_CONF_NEGATIVE)
    def test_invalid_relate_ticket_minutes_valid_after_use_negative(self):
        self.assertEqual([r.id for r in self.func(None)],
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
        self.assertEqual(self.func(None), [])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_NONE)
    def test_invalid_git_root_none(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E001"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_LIST)
    def test_invalid_git_root_list(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E002"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_SPACES)
    def test_invalid_git_root_spaces(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E003"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_NOT_DIR)
    def test_invalid_git_root(self, mocked_os_access, mocked_os_path_is_dir):
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E003"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_W_FAIL)
    def test_invalid_git_root_no_write_perm(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no write permission
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E004"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_R_FAIL)
    def test_invalid_git_root_no_read_perms(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no read permission
        self.assertEqual([r.id for r in self.func(None)],
                         ["git_root.E005"])

    @override_settings(GIT_ROOT=INVALID_GIT_ROOT_W_R_FAIL)
    def test_invalid_git_root_no_both_perms(
            self, mocked_os_access, mocked_os_path_is_dir):
        # no write and read permissions
        result = self.func(None)
        self.assertEqual(len(result), 2)
        self.assertEqual([r.id for r in result],
                         ["git_root.E004", "git_root.E005"])
