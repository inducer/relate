# -*- coding: utf-8 -*-

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

try:
    from test.support import EnvironmentVarGuard  # noqa
except ImportError:
    from test.test_support import EnvironmentVarGuard  # noqa

from django.test import override_settings

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

    import sys
    if sys.platform.startswith("win"):
        return True

    if sys.platform.startswith("darwin"):
        return True

    return False


skip_real_docker_test = _skip_real_docker_test()
SKIP_REAL_DOCKER_REASON = "These are tests for real docker"

REAL_RELATE_DOCKER_URL = "unix:///var/run/docker.sock"
REAL_RELATE_DOCKER_TLS_CONFIG = None
REAL_RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runpy-i386"


class RealDockerTestMixin(object):
    """
    This is used for code question test with real docker container.
    Note: the test speed is slow when using this mixin.
    """

    @classmethod
    def setUpClass(cls):  # noqa
        from unittest import SkipTest
        if skip_real_docker_test:
            raise SkipTest(SKIP_REAL_DOCKER_REASON)

        super(RealDockerTestMixin, cls).setUpClass()
        cls.override_docker_settings = override_settings(
            RELATE_DOCKER_URL=REAL_RELATE_DOCKER_URL,
            RELATE_DOCKER_RUNPY_IMAGE=REAL_RELATE_DOCKER_RUNPY_IMAGE,
            RELATE_DOCKER_TLS_CONFIG=REAL_RELATE_DOCKER_TLS_CONFIG
        )
        cls.override_docker_settings.enable()
        cls.make_sure_docker_image_pulled()

    @classmethod
    def tearDownClass(cls):  # noqa
        super(RealDockerTestMixin, cls).tearDownClass()
        cls.override_docker_settings.disable()

    @classmethod
    def make_sure_docker_image_pulled(cls):
        import docker
        cli = docker.Client(
            base_url=REAL_RELATE_DOCKER_URL,
            tls=None,
            timeout=15,
            version="1.19")

        if not bool(cli.images(REAL_RELATE_DOCKER_RUNPY_IMAGE)):
            # This should run only once and get cached on Travis-CI
            cli.pull(REAL_RELATE_DOCKER_RUNPY_IMAGE)
