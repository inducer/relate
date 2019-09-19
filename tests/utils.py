from __future__ import division

import sys
try:
    from importlib import reload
except ImportError:
    pass  # PY2
import os
from importlib import import_module
import six
from six import StringIO
from functools import wraps

from django.urls import clear_url_caches
from django.conf import settings
from django.test import override_settings
from django.core import mail
try:
    # for Django < 2.0
    from django.test import mock  # noqa
except ImportError:
    # Since Django >= 2.0 only support PY3
    from unittest import mock  # noqa

    if sys.version_info < (3, 8):
        # __round__ is missing from MagicMock before Py3.8
        # https://github.com/python/cpython/pull/6880
        # Work around this by monkeypatching mock:
        mock._magics.add("__round__")
        mock._all_magics = mock._magics | mock._non_defaults


# {{{ These are copied (and maybe modified) from django official unit tests
class BaseEmailBackendTestsMixin(object):
    email_backend = None

    def setUp(self):  # noqa
        super(BaseEmailBackendTestsMixin, self).setUp()
        self.email_backend_settings_override = (
            override_settings(EMAIL_BACKEND=self.email_backend))
        self.email_backend_settings_override.enable()
        self.addCleanup(self.email_backend_settings_override.disable)

    def assertStartsWith(self, first, second):  # noqa
        if not first.startswith(second):
            self.longMessage = True
            self.assertEqual(first[:len(second)], second,
                             "First string doesn't start with the second.")

    def get_mailbox_content(self):
        raise NotImplementedError(
            'subclasses of BaseEmailBackendTests must provide '
            'a get_mailbox_content() method')

    def flush_mailbox(self):
        raise NotImplementedError('subclasses of BaseEmailBackendTests may '
                                  'require a flush_mailbox() method')

    def get_the_email_message(self):
        mailbox = self.get_mailbox_content()
        self.assertEqual(
            len(mailbox), 1,
            "Expected exactly one message, got %d.\n%r"
            % (len(mailbox), [m.as_string() for m in mailbox])
        )
        return mailbox[0]

    def get_the_latest_message(self):
        mailbox = self.get_mailbox_content()
        self.assertGreater(
            len(mailbox), 0,
            "Expected at least one message, got %d.\n%r"
            % (len(mailbox), [m.as_string() for m in mailbox])
        )
        return mailbox[-1]

    def debug_print_email_messages(self, indices=None):
        """
        For debugging  print email contents with indices in outbox
        """
        messages = self.get_mailbox_content()
        if indices is not None:
            if not isinstance(indices, list):
                assert isinstance(indices, int)
                indices = [indices]
            else:
                for i in indices:
                    assert isinstance(i, int)
        else:
            indices = list(range(len(messages)))
        for i in indices:
            try:
                msg = messages[i]
                print("\n-----------email (%i)-------------" % i)
                print(msg)
            except KeyError:
                print("\n-------no email with index %i----------" % i)
            finally:
                print("\n------------------------")


class LocmemBackendTestsMixin(BaseEmailBackendTestsMixin):
    email_backend = 'django.core.mail.backends.locmem.EmailBackend'

    def get_mailbox_content(self):
        return [m.message() for m in mail.outbox]

    def flush_mailbox(self):
        mail.outbox = []

    def tearDown(self):  # noqa
        super(LocmemBackendTestsMixin, self).tearDown()
        mail.outbox = []


# }}}


class suppress_stdout_decorator(object):  # noqa
    def __init__(self, suppress_stderr=False):
        self.original_stdout = None
        self.suppress_stderr = None
        self.suppress_stderr = suppress_stderr

    def __enter__(self):
        self.original_stdout = sys.stdout
        sys.stdout = StringIO()

        if self.suppress_stderr:
            self.original_stderr = sys.stderr
            sys.stderr = StringIO()

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        if self.suppress_stderr:
            sys.stderr = self.original_stderr

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kw):
            with self:
                return func(*args, **kw)

        return wrapper


def load_url_pattern_names(patterns):
    """Retrieve a list of urlpattern names"""
    url_names = []
    for pat in patterns:
        if pat.__class__.__name__ == 'RegexURLResolver':
            load_url_pattern_names(pat.url_patterns)
        elif pat.__class__.__name__ == 'RegexURLPattern':
            if pat.name is not None and pat.name not in url_names:
                url_names.append(pat.name)
        else:
            from django.urls import URLPattern
            assert isinstance(pat, URLPattern)
            url_names.append(pat.name)
    return url_names


def reload_urlconf(urlconf=None):
    """Reload urlconf, this should be used when some urlpatterns are included
    according to settings
    """
    clear_url_caches()
    if urlconf is None:
        urlconf = settings.ROOT_URLCONF
    if urlconf in sys.modules:
        reload(sys.modules[urlconf])
    else:
        import_module(urlconf)


def _is_connection_psql():
    from django.db import connection
    return connection.vendor == 'postgresql'


is_connection_psql = _is_connection_psql()


SKIP_NON_PSQL_REASON = "PostgreSQL specific SQL used"


def may_run_expensive_tests():
    if six.PY2:
        return False

    # Allow run expensive tests locally, i.e., CI not detected.
    if not any([os.getenv(ci)
                for ci in ["RL_CI_TEST", "GITLAB_CI", "APPVEYOR"]]):
        return True

    if os.getenv("RL_CI_TEST") != "test_expensive":
        return False

    return True


SKIP_EXPENSIVE_TESTS_REASON = (
    "This expensive test is ran separately on TRAVIS-CI with test_expensive "
    "env variable, or local tests.")

# vim: fdm=marker
