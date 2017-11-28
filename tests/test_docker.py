# -*- coding: utf-8 -*-

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

from .utils import mock

try:
    from test.support import EnvironmentVarGuard  # noqa
except:
    from test.test_support import EnvironmentVarGuard  # noqa

from unittest import skipIf
from copy import deepcopy
from django.conf import settings
from django.core import mail

from django.test.utils import override_settings
from django.test import SimpleTestCase
from course.docker.config import (
    get_docker_client_config, get_relate_runpy_docker_client_config)

from django.core.exceptions import ImproperlyConfigured
from relate.utils import is_windows_platform, is_osx_platform
import docker.tls
import warnings

from course.docker.config import (  # noqa
    DEFAULT_DOCKER_RUNPY_CONFIG_ALIAS,

    DOCKER_HOST,
    DOCKER_CERT_PATH,
    DOCKER_TLS_VERIFY,

    RELATE_RUNPY_DOCKER_ENABLED,
    RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME,

    RELATEDeprecateWarning,

    RELATE_DOCKERS,
    RunpyClientForDockerConfigure,
    RunpyClientForDockerMachineConfigure,
    ClientForDockerConfigure,
    ClientForDockerMachineConfigure,

    RunpyDockerClientConfigNameIsNoneWarning,
)
from django.test import TestCase
from .base_test_mixins import SingleCoursePageTestMixin
from .test_pages import QUIZ_FLOW_ID

# Switch for test locally
Debug = False

GITLAB_CI = "GITLAB_CI"
APPVEYOR_CI = "APPVEYOR"

# Controller in CI scripts
ENABLE_DOCKER_TEST = "ENABLE_DOCKER_TEST"


def _skip_real_docker_test():
    import os

    # Skipping CI
    for skipped_ci in [GITLAB_CI, APPVEYOR_CI]:
        if os.environ.get(skipped_ci):
            print("Running on %s" % skipped_ci)
            return True

    # For debugging on local Windows or Mac
    if Debug:
        # Uncomment for tests in Windows when docker-machine is not started
        # for env_variable in [DOCKER_HOST, DOCKER_CERT_PATH, DOCKER_TLS_VERIFY]:
        #     if env_variable not in os.environ:
        #         return True
        return False

    # Skipping CI test which do not need docker (pep8, mypy)
    enable_docker_test = os.environ.get(ENABLE_DOCKER_TEST)
    if enable_docker_test is None:
        return True

    return False


skip_real_docker_test = _skip_real_docker_test()
SKIP_REAL_DOCKER_REASON = "These are tests for real docker"

ORIGINAL_RELATE_DOCKER_TLS_CONFIG = docker.tls.TLSConfig()
ORIGINAL_RELATE_DOCKER_URL = "http://original.url.net:2376"
ORIGINAL_RELATE_DOCKER_RUNPY_IMAGE = "runpy_original.image"

TEST_TLS = docker.tls.TLSConfig()


TEST_DOCKERS = {
    "runpy_test": {
        "docker_image": "runpy_test.image",
        "client_config": {
            "base_url": "http://some.url.net:2376",
            "tls": TEST_TLS,
            "timeout": 15,
            "version": "1.19"
        },
        "local_docker_machine_config": {
            "enabled": True,
            "config": {
                "shell": None,
                "name": "default",
            },
        },
        "private_public_ip_map_dict": {
            "192.168.1.100": "192.168.100.100"},
    },
}

TEST_DOCKERS["no_image"] = deepcopy(TEST_DOCKERS["runpy_test"])
del TEST_DOCKERS["no_image"]["docker_image"]

TEST_DOCKERS["no_base_url"] = deepcopy(TEST_DOCKERS["runpy_test"])
TEST_DOCKERS["no_base_url"]["client_config"].pop("base_url")

TEST_DOCKERS["no_tls"] = deepcopy(TEST_DOCKERS["runpy_test"])
del TEST_DOCKERS["no_tls"]["client_config"]["tls"]

TEST_DOCKERS["no_local_docker_machine_config"] = (
    deepcopy(TEST_DOCKERS["runpy_test"]))
TEST_DOCKERS["no_local_docker_machine_config"].pop("local_docker_machine_config")

TEST_DOCKERS["local_docker_machine_config_not_enabled"] = (
    deepcopy(TEST_DOCKERS["runpy_test"]))
TEST_DOCKERS[
    "local_docker_machine_config_not_enabled"][
    "local_docker_machine_config"]["enabled"] = False

VALID_RUNPY_CONFIG_NAME = "runpy_test"
RUNPY_DOCKER_CONFIG_NAME_NO_IMAGE = "no_image"
RUNPY_DOCKER_CONFIG_NAME_NO_BASE_URL = "no_base_url"
RUNPY_DOCKER_CONFIG_NAME_NO_TLS = "no_tls"
RUNPY_DOCKER_CONFIG_NAME_NO_DOCKER_MACHINE = "no_local_docker_machine_config"
RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED = (
    "local_docker_machine_config_not_enabled")

RUNPY_DOCKER_CONFIG_NAME_NOT_EXIST = "not_exist_config"
TEST_DOCKERS.pop(RUNPY_DOCKER_CONFIG_NAME_NOT_EXIST, None)


TEST_DOCKERS_WITH_DEFAULT_CONFIG = {
    DEFAULT_DOCKER_RUNPY_CONFIG_ALIAS: {
        "docker_image": "runpy_default.image",
        "client_config": {
            "base_url": "http://default.url.net",
            "tls": docker.tls.TLSConfig(),
            "timeout": 15,
            "version": "1.19"
        }
    }
}


@override_settings(RELATE_RUNPY_DOCKER_ENABLED=True,
                   RELATE_DOCKERS=TEST_DOCKERS,
                   RELATE_DOCKER_RUNPY_IMAGE="Original.image",
                   RELATE_DOCKER_TLS_CONFIG=docker.tls.TLSConfig(),
                   RELATE_DOCKER_URL="http://original.url")
class ClientConfigGetFunctionTests(SimpleTestCase):
    """
    test course.docker.config.get_docker_client_config
    """
    @mock.patch("course.docker.config.is_windows_platform", return_value=True)
    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=VALID_RUNPY_CONFIG_NAME)
    def test_config_instance_windows(self, mocked_sys):
        result = get_docker_client_config(VALID_RUNPY_CONFIG_NAME, for_runpy=True)
        self.assertIsInstance(result, RunpyClientForDockerMachineConfigure)
        self.assertEqual(result.image, "runpy_test.image")

        result = get_docker_client_config(VALID_RUNPY_CONFIG_NAME, for_runpy=False)
        self.assertIsInstance(result, ClientForDockerMachineConfigure)
        with self.assertRaises(AttributeError):
            result.image

        result = get_relate_runpy_docker_client_config(silence_if_not_usable=False)
        self.assertIsInstance(result, RunpyClientForDockerMachineConfigure)
        self.assertEqual(result.image, "runpy_test.image")

    @mock.patch("course.docker.config.is_windows_platform", return_value=False)
    @mock.patch("course.docker.config.is_windows_platform", return_value=False)
    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=VALID_RUNPY_CONFIG_NAME)
    def test_config_instance_not_windows(
            self, mocked_sys1, mocked_sys2):
        result = get_docker_client_config(VALID_RUNPY_CONFIG_NAME, for_runpy=True)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")

        result = get_docker_client_config(VALID_RUNPY_CONFIG_NAME, for_runpy=False)
        self.assertIsInstance(result, ClientForDockerConfigure)
        with self.assertRaises(AttributeError):
            result.image

        result = get_relate_runpy_docker_client_config(silence_if_not_usable=False)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")

    @mock.patch("course.docker.config.is_windows_platform", return_value=True)
    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED)  # noqa
    def test_config_instance_docker_machine_not_enabled_windows(
            self, mocked_sys):
        result = get_docker_client_config(
            RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED, for_runpy=True)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")

        result = get_docker_client_config(
            RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED, for_runpy=False)
        self.assertIsInstance(result, ClientForDockerConfigure)
        with self.assertRaises(AttributeError):
            result.image

        result = get_relate_runpy_docker_client_config(silence_if_not_usable=False)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")

    @mock.patch("course.docker.config.is_windows_platform", return_value=False)
    @mock.patch("course.docker.config.is_osx_platform", return_value=False)
    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED)  # noqa
    def test_config_instance_docker_machine_not_enabled_not_windows(
            self, mocked_sys1, mocked_sys2):
        result = get_docker_client_config(
            RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED,
            for_runpy=True)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")

        result = get_docker_client_config(
            RUNPY_DOCKER_CONFIG_NAME_DOCKER_MACHINE_NOT_ENABLED,
            for_runpy=False)
        self.assertIsInstance(result, ClientForDockerConfigure)
        with self.assertRaises(AttributeError):
            result.image

        result = get_relate_runpy_docker_client_config(silence_if_not_usable=False)
        self.assertIsInstance(result, RunpyClientForDockerConfigure)
        self.assertEqual(result.image, "runpy_test.image")


@override_settings(RELATE_DOCKERS=TEST_DOCKERS_WITH_DEFAULT_CONFIG)
class DefaultConfigClientConfigGetFunctionTests(SimpleTestCase):
    """
    Test RELATE_DOCKS contains a configure named "default"
    (DEFAULT_DOCKER_RUNPY_CONFIG_ALIAS)
    """
    @override_settings(RELATE_RUNPY_DOCKER_ENABLED=True,

                       # Explicitly set to None
                       RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=None)
    def test_get_runpy_config_explicitly_named_none(self):
        self.assertTrue(hasattr(settings, RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME))

        expected_msg = ("%s can not be None when %s is True"
               % (RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME,
                  RELATE_RUNPY_DOCKER_ENABLED))
        with self.assertRaisesMessage(ImproperlyConfigured, expected_msg):
            get_relate_runpy_docker_client_config(silence_if_not_usable=False)

        with warnings.catch_warnings(record=True) as warns:
            self.assertIsNone(
                get_relate_runpy_docker_client_config(silence_if_not_usable=True))
            self.assertEqual(len(warns), 1)
            self.assertIsInstance(
                warns[0].message, RunpyDockerClientConfigNameIsNoneWarning)
            self.assertEqual(str(warns[0].message), expected_msg)

    @override_settings(RELATE_RUNPY_DOCKER_ENABLED=True)
    def test_get_runpy_config_not_named1(self):
        # simulate RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME is not configured
        with self.settings():
            if hasattr(settings, RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME):
                del settings.RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME
            self.assertRaises(AttributeError, getattr,
                              settings, RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME)
            result = get_relate_runpy_docker_client_config(
                silence_if_not_usable=False)
            self.assertEqual(result.image, "runpy_default.image")

    @override_settings(RELATE_RUNPY_DOCKER_ENABLED=False,
                       RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=None,
                       SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR=True)
    def test_get_runpy_config_not_named_not_enabled2(self):
        result = get_relate_runpy_docker_client_config(
            silence_if_not_usable=settings.SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR)
        self.assertIsNone(result)


@override_settings(RELATE_DOCKERS=TEST_DOCKERS, RELATE_RUNPY_DOCKER_ENABLED=True)
class DeprecationWarningsTests(SimpleTestCase):
    @override_settings(
        RELATE_DOCKER_URL=ORIGINAL_RELATE_DOCKER_URL,
        RELATE_DOCKER_TLS_CONFIG=ORIGINAL_RELATE_DOCKER_TLS_CONFIG,
        RELATE_DOCKER_RUNPY_IMAGE=ORIGINAL_RELATE_DOCKER_RUNPY_IMAGE,
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_NO_IMAGE
    )
    def test_no_relate_dockers(self):
        with self.settings():
            del settings.RELATE_DOCKERS
            del settings.RELATE_RUNPY_DOCKER_ENABLED
            with warnings.catch_warnings(record=True) as warns:
                self.assertIsNotNone(
                    get_relate_runpy_docker_client_config())
                self.assertEqual(len(warns), 1)
                self.assertIsInstance(
                    warns[0].message, RELATEDeprecateWarning)

    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_NO_IMAGE
    )
    def test_no_image(self):
        with override_settings(
                RELATE_DOCKER_RUNPY_IMAGE=ORIGINAL_RELATE_DOCKER_RUNPY_IMAGE):
            with warnings.catch_warnings(record=True) as warns:
                self.assertIsNotNone(
                    get_relate_runpy_docker_client_config())
                self.assertEqual(len(warns), 1)
                self.assertIsInstance(
                    warns[0].message, RELATEDeprecateWarning)

            with self.settings():
                del settings.RELATE_DOCKER_RUNPY_IMAGE
                with self.assertRaises(ImproperlyConfigured):
                    get_relate_runpy_docker_client_config()

    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_NO_BASE_URL
    )
    def test_no_base_url(self):
        with override_settings(
                RELATE_DOCKER_URL=ORIGINAL_RELATE_DOCKER_URL):
            with warnings.catch_warnings(
                    record=True) as warns:
                self.assertIsNotNone(
                    get_relate_runpy_docker_client_config())
                if is_windows_platform() or is_osx_platform():
                    # because local_docker_machine_config is enabled
                    self.assertEqual(len(warns), 0)
                else:
                    self.assertEqual(len(warns), 1)
                    self.assertIsInstance(
                        warns[0].message,
                        RELATEDeprecateWarning)

            with self.settings():
                del settings.RELATE_DOCKER_URL
                if is_windows_platform() or is_osx_platform():
                    self.assertIsNotNone(
                        get_relate_runpy_docker_client_config())
                else:
                    with self.assertRaises(
                            ImproperlyConfigured):
                        get_relate_runpy_docker_client_config()

    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_NO_TLS
    )
    def test_no_tls(self):
        with override_settings(
                RELATE_DOCKER_TLS_CONFIG=ORIGINAL_RELATE_DOCKER_TLS_CONFIG):
            with warnings.catch_warnings(
                    record=True) as warns:
                self.assertIsNotNone(
                    get_relate_runpy_docker_client_config())
                if is_windows_platform() or is_osx_platform():
                    # because local_docker_machine_config is enabled
                    self.assertEqual(len(warns), 0)
                else:
                    self.assertEqual(len(warns), 1)
                    self.assertIsInstance(
                        warns[0].message,
                        RELATEDeprecateWarning)


@override_settings(RELATE_DOCKERS=TEST_DOCKERS)
class NotDefinedConfigClientConfigGetFunctionTests(SimpleTestCase):
    @mock.patch(
        "relate.utils.is_windows_platform", return_value=True)
    @override_settings(
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=RUNPY_DOCKER_CONFIG_NAME_NOT_EXIST)  # noqa
    def test_get_runpy_config_with_not_exist_config_name(self, mocked_sys):
        with override_settings(RELATE_RUNPY_DOCKER_ENABLED=True):
            expected_error_msg = (
                "RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME: "
                "RELATE_DOCKERS "
                "has no configuration named 'not_exist_config'")
            with self.assertRaises(ImproperlyConfigured) as cm:
                get_relate_runpy_docker_client_config(
                    silence_if_not_usable=False)
            self.assertEqual(str(cm.exception), expected_error_msg)

        with override_settings(
                RELATE_RUNPY_DOCKER_ENABLED=False,
                SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR=True):
            result = (
                get_relate_runpy_docker_client_config(
                    silence_if_not_usable=settings.SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR))  # noqa
            self.assertIsNone(result)
            result = (
                get_relate_runpy_docker_client_config(
                    silence_if_not_usable=True))
            self.assertIsNone(result)


REAL_RELATE_DOCKER_URL = "unix:///var/run/docker.sock"
REAL_RELATE_DOCKER_TLS_CONFIG = None
REAL_RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runpy-i386"

REAL_DOCKERS = {
    "runpy": {
        "docker_image": REAL_RELATE_DOCKER_RUNPY_IMAGE,
        "client_config": {
            "base_url": REAL_RELATE_DOCKER_URL,
            "tls": REAL_RELATE_DOCKER_TLS_CONFIG,
            "timeout": 15,
            "version": "1.19"
        },
        "local_docker_machine_config": {
            "enabled": True,
            "config": {
                "shell": None,
                "name": "default",
            },
        },
        "private_public_ip_map_dict": {
            "192.168.1.100": "192.168.100.100"},
    },
}

REAL_RUNPY_CONFIG_NAME = "runpy"

REAL_DOCKERS_WITH_UNPULLED_IMAGE = deepcopy(REAL_DOCKERS)
REAL_DOCKERS_WITH_UNPULLED_IMAGE[REAL_RUNPY_CONFIG_NAME]["docker_image"] = (
    "some/unpulled/repo"
)
REAL_DOCKERS_WITH_INVALID_IP_MAP = deepcopy(REAL_DOCKERS)
REAL_DOCKERS_WITH_INVALID_IP_MAP[REAL_RUNPY_CONFIG_NAME]["private_public_ip_map_dict"] = (  # noqa
    {"localhost": "another_ip"}
)


class RealDockerTestMixin(object):
    def setUp(self):
        super(RealDockerTestMixin, self).setUp()
        self.make_sure_docker_image_pulled()

    def make_sure_docker_image_pulled(self):
        if skip_real_docker_test:
            return
        with self.settings():
            settings.RELATE_DOCKERS = REAL_DOCKERS
            settings.RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME = REAL_RUNPY_CONFIG_NAME
            client_config = get_relate_runpy_docker_client_config(
                silence_if_not_usable=False)
            cli = client_config.create_client()
            if not bool(cli.images(REAL_RELATE_DOCKER_RUNPY_IMAGE)):
                # This should run only once and get cached on Travis-CI
                cli.pull(client_config.image)


@skipIf(skip_real_docker_test, SKIP_REAL_DOCKER_REASON)
@override_settings(
    RELATE_RUNPY_DOCKER_ENABLED=True,
    RELATE_DOCKERS=REAL_DOCKERS,
    RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=REAL_RUNPY_CONFIG_NAME
)
class RealDockerTests(RealDockerTestMixin, SimpleTestCase):
    def test_get_real_docker_client_config(self):
        result = get_relate_runpy_docker_client_config(silence_if_not_usable=False)
        self.assertIsInstance(
            result,
            (RunpyClientForDockerConfigure,
             RunpyClientForDockerMachineConfigure)
        )


def get_docker_program_version_none(program, print_output=False):
    return None


def get_docker_program_version_outdated(program, print_output=False):
    if program == "docker":
        return "1.5.9"
    else:
        return "0.6.9"


def get_docker_program_version_machine_outdated(program, print_output=False):
    if program == "docker":
        return "1.7.1"
    else:
        return "0.6.9"


class UnknownGetVersionException(Exception):
    pass


def get_docker_program_version_exception_both(program, print_output=False):
    raise UnknownGetVersionException()


def get_docker_program_version_exception_machine(program, print_output=False):
    if program == "docker":
        return "1.7.1"
    else:
        raise UnknownGetVersionException()


@skipIf(skip_real_docker_test, SKIP_REAL_DOCKER_REASON)
@override_settings(
    RELATE_RUNPY_DOCKER_ENABLED=True,
    RELATE_DOCKERS=REAL_DOCKERS,
    RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=REAL_RUNPY_CONFIG_NAME
)
class RealRunpyDockerCheck(RealDockerTestMixin, SimpleTestCase):
    @property
    def func(self):
        from course.docker.checks import check_docker_client_config
        return check_docker_client_config

    def test_tls_not_configured_warning(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result], ["docker_config_client_tls.W001"])

    @override_settings(RELATE_DOCKERS=REAL_DOCKERS_WITH_UNPULLED_IMAGE)
    def test_image_not_pulled_error(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result], ["docker_config_client_tls.W001",
                                                  "docker_config_image.E001"])

    @mock.patch("course.docker.config.get_docker_program_version",
                side_effect=get_docker_program_version_none)
    def test_docker_version_none(self, mocked_get_version):
        result = self.func(None)
        if is_windows_platform() or is_osx_platform():
            self.assertEqual([r.id for r in result],
                             ["docker_version.E001",
                              'docker_machine_version.E001'])
        else:
            self.assertEqual([r.id for r in result],
                             ["docker_version.E001"])

    @mock.patch("course.docker.config.get_docker_program_version",
                side_effect=get_docker_program_version_outdated)
    def test_docker_version_outdated(self, mocked_get_version):
        result = self.func(None)
        if is_windows_platform() or is_osx_platform():
            self.assertEqual([r.id for r in result],
                             ["docker_version.E001",
                              'docker_machine_version.E001'])
        else:
            self.assertEqual([r.id for r in result],
                             ["docker_version.E001"])

    @mock.patch("course.docker.config.get_docker_program_version",
                side_effect=get_docker_program_version_machine_outdated)
    def test_docker_version_machine_outdated(self, mocked_get_version):
        result = self.func(None)
        if is_windows_platform() or is_osx_platform():
            self.assertEqual([r.id for r in result],
                             ["docker_machine_version.E001"])
        else:
            self.assertEqual([r.id for r in result],
                             ["docker_config_client_tls.W001"])

    @mock.patch("course.docker.config.get_docker_program_version",
                side_effect=get_docker_program_version_exception_both)
    def test_docker_version_exception_both(self, mocked_get_version):
        result = self.func(None)
        if is_windows_platform() or is_osx_platform():
            self.assertEqual([r.id for r in result],
                             ["docker_version_exception_unknown.E001",
                              "docker_machine_version_exception_unknown.E001"])
        else:
            self.assertEqual([r.id for r in result],
                             ["docker_version_exception_unknown.E001"])

    @mock.patch("course.docker.config.get_docker_program_version",
                side_effect=get_docker_program_version_exception_machine)
    def test_docker_version_exception_machine(self, mocked_get_version):
        result = self.func(None)
        if is_windows_platform() or is_osx_platform():
            self.assertEqual([r.id for r in result],
                             ["docker_machine_version_exception_unknown.E001"])
        else:
            self.assertEqual([r.id for r in result],
                             ["docker_config_client_tls.W001"])

    @override_settings(
        RELATE_RUNPY_DOCKER_ENABLED=True,
        RELATE_DOCKERS=REAL_DOCKERS_WITH_INVALID_IP_MAP,
        RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=REAL_RUNPY_CONFIG_NAME)
    def test_private_public_ip_map_dict_check(self):
        result = self.func(None)
        self.assertEqual([r.id for r in result],
                         ['private_public_ip_map_dict.E001'])


@skipIf(skip_real_docker_test, SKIP_REAL_DOCKER_REASON)
@override_settings(
    RELATE_RUNPY_DOCKER_ENABLED=True,
    RELATE_DOCKERS=REAL_DOCKERS,
    RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=REAL_RUNPY_CONFIG_NAME
)
class RealDockerCodePageTest(SingleCoursePageTestMixin,
                             RealDockerTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID
    page_id = "addition"

    def setUp(self):  # noqa
        super(RealDockerCodePageTest, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_quiz(self.flow_id)

    @skipIf(is_windows_platform(), "docker-machine is not availabe in this case")
    @skipIf(is_osx_platform(), "docker-machine is not availabe in this case")
    @override_settings(RELATE_DOCKER_URL=REAL_RELATE_DOCKER_URL,
                       RELATE_DOCKER_TLS_CONFIG=REAL_RELATE_DOCKER_TLS_CONFIG,
                       RELATE_DOCKER_RUNPY_IMAGE=REAL_RELATE_DOCKER_RUNPY_IMAGE)
    def test_code_page_with_deprecated_config(self):
        with self.settings():
            del settings.RELATE_DOCKERS
            del settings.RELATE_RUNPY_DOCKER_ENABLED
            del settings.SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR
            answer_data = {"answer": "c = a + b"}
            expected_str = (
                "It looks like you submitted code that is identical to "
                "the reference solution. This is not allowed.")
            resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
            self.assertContains(resp, expected_str, count=1)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.end_quiz().status_code, 200)
            self.assertSessionScoreEqual(1)

    def test_code_page_with_relate_runpy_docker_enabled_not_configured(self):
        with self.settings():
            del settings.RELATE_RUNPY_DOCKER_ENABLED
            answer_data = {"answer": "c = a + b"}
            expected_str = (
                "It looks like you submitted code that is identical to "
                "the reference solution. This is not allowed.")
            resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
            self.assertContains(resp, expected_str, count=1)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.end_quiz().status_code, 200)
            self.assertSessionScoreEqual(1)

    def test_code_page_correct_answer(self):
        answer_data = {"answer": "c = a + b"}
        expected_str = (
            "It looks like you submitted code that is identical to "
            "the reference solution. This is not allowed.")
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertContains(resp, expected_str, count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_code_page_wrong_answer(self):
        answer_data = {"answer": "c = a - b"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_code_page_user_code_exception_raise(self):
        answer_data = {"answer": "c = a ^ b"}
        from django.utils.html import escape
        expected_error_str1 = escape(
            "Your code failed with an exception. "
            "A traceback is below.")
        expected_error_str2 = escape(
            "TypeError: unsupported operand type(s) for ^: "
            "'float' and 'float'")
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, expected_error_str1, count=1)
        self.assertContains(resp, expected_error_str2, count=1)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)


UNCAUGHT_ERROR = {
    "result": "uncaught_error",
    "message": "uncaught error",
    "traceback": "traceback for uncaught error",
    "exec_host": "local_host",
}

SETUP_COMPILE_ERROR = {
    "result": "setup_compile_error",
    "message": "setup compile error",
    "traceback": "traceback for setup compile error",
    "exec_host": "local_host",
}

USER_COMPILE_ERROR = {
    "result": "user_compile_error",
    "message": "user compile error",
    "traceback": "traceback for user compile error",
    "exec_host": "local_host",
}

TIMEOUT_RESULT = {
    "result": "timeout",
    "message": "Timeout waiting for container.",
    "traceback": "traceback for timeout",
    "exec_host": "local_host",
}

DOCKER_RUNPY_NOT_ENABLED_ERROR = {
    "result": "docker_runpy_not_enabled",
    "message": "docker runpy not enabled",
    "traceback": "traceback for no docker",
}


@override_settings(
    RELATE_RUNPY_DOCKER_ENABLED=True,
    RELATE_DOCKERS=TEST_DOCKERS,
    RELATE_RUNPY_DOCKER_CLIENT_CONFIG_NAME=VALID_RUNPY_CONFIG_NAME,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class CodePageTestOther(SingleCoursePageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID
    page_id = "addition"

    def setUp(self):  # noqa
        super(CodePageTestOther, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_quiz(self.flow_id)

    def tearDown(self):
        super(CodePageTestOther, self).tearDown()
        mail.outbox = []

    @mock.patch("course.page.code.request_python_run",
                return_value={"result": "success"})
    @mock.patch("course.docker.config.RunpyDockerMixinBase.get_public_accessible_ip")  # noqa
    def test_code_page_success(self,
                               mocked_request_python_run, mock_get_public_acc_ip):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(mock_get_public_acc_ip.call_count, 1)

        # call again
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(mock_get_public_acc_ip.call_count, 2)

        self.assertEqual(resp.status_code, 200)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 0)

    @mock.patch("course.page.code.request_python_run",
                return_value=UNCAUGHT_ERROR)
    def test_code_page_uncaught_error(self, mocked_request_python_run):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 1)

    @mock.patch("course.page.code.request_python_run",
                return_value=SETUP_COMPILE_ERROR)
    def test_code_page_setup_compile_error(self, mocked_request_python_run):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)

        # again
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 2)

    @mock.patch("course.page.code.request_python_run",
                return_value=USER_COMPILE_ERROR)
    def test_code_page_user_compile_error(self, mocked_request_python_run):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 0)

    @mock.patch("course.page.code.request_python_run",
                return_value=TIMEOUT_RESULT)
    def test_code_page_run_timeout(self, mocked_request_python_run):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        RELATE_RUNPY_DOCKER_ENABLED=False,
        SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR=False
    )
    def test_code_page_docker_not_enabled_not_silenced(self):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Runpy docker is not usable with %s=%s"
            % (RELATE_RUNPY_DOCKER_ENABLED, settings.RELATE_RUNPY_DOCKER_ENABLED),
            count=1)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 1)
        # self.assert

    @override_settings(
        RELATE_RUNPY_DOCKER_ENABLED=False,
    )
    def test_code_page_docker_not_enabled_unconfigure_silence(self):
        with self.settings():
            del settings.SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR
            answer_data = {"answer": "some code"}
            resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(
                resp,
                "Runpy docker is not usable with %s=%s"
                % (
                    RELATE_RUNPY_DOCKER_ENABLED,
                    settings.RELATE_RUNPY_DOCKER_ENABLED),
                count=1)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        RELATE_RUNPY_DOCKER_ENABLED=False,
        SILENCE_RUNPY_DOCKER_NOT_USABLE_ERROR=True
    )
    def test_code_page_docker_enabled_silenced(self):
        answer_data = {"answer": "some code"}
        resp = self.client_post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "Docker runpy is currently not enabled for this site",
            count=1)
        self.end_quiz()
        self.assertEqual(len(mail.outbox), 0)
