from __future__ import division

import sys
from six import StringIO
from functools import wraps
from django.test import override_settings
from django.core import mail


# {{{ These are copied (and maybe modified) from django official unit tests
class BaseEmailBackendTestsMixin(object):
    email_backend = None

    def setUp(self):  # noqa
        self.settings_override = override_settings(EMAIL_BACKEND=self.email_backend)
        self.settings_override.enable()

    def tearDown(self):  # noqa
        self.settings_override.disable()

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


class BaseEmailBackendTestsMixin(object):
    email_backend = None

    def setUp(self):  # noqa
        self.settings_override = override_settings(EMAIL_BACKEND=self.email_backend)
        self.settings_override.enable()

    def tearDown(self):  # noqa
        self.settings_override.disable()

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

# vim: fdm=marker
