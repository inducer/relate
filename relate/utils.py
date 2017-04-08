# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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
import datetime

import django.forms as forms
import dulwich.repo

from typing import Union

if False:
    from typing import Text, List, Dict, Tuple, Optional, Any  # noqa


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        # type: (...) -> None
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(StyledForm, self).__init__(*args, **kwargs)


class StyledInlineForm(forms.Form):
    def __init__(self, *args, **kwargs):
        # type: (...) -> None

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-inline"
        self.helper.label_class = "sr-only"

        super(StyledInlineForm, self).__init__(*args, **kwargs)


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        # type: (...) -> None

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(StyledModelForm, self).__init__(*args, **kwargs)


# {{{ repo-ish types

class SubdirRepoWrapper(object):
    def __init__(self, repo, subdir):
        # type: (dulwich.Repo, Text) -> None
        self.repo = repo

        # This wrapper should only get used if there is a subdir to be had.
        assert subdir
        self.subdir = subdir

    def controldir(self):
        return self.repo.controldir()

    def close(self):
        self.repo.close()


Repo_ish = Union[dulwich.repo.Repo, SubdirRepoWrapper]

# }}}


# {{{ maintenance mode

def is_maintenance_mode(request):
    from django.conf import settings
    maintenance_mode = getattr(settings, "RELATE_MAINTENANCE_MODE", False)

    if maintenance_mode:
        exceptions = getattr(settings, "RELATE_MAINTENANCE_MODE_EXCEPTIONS", [])

        import ipaddress

        remote_address = ipaddress.ip_address(
                six.text_type(request.META['REMOTE_ADDR']))

        for exc in exceptions:
            if remote_address in ipaddress.ip_network(six.text_type(exc)):
                maintenance_mode = False
                break

    return maintenance_mode


class MaintenanceMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_maintenance_mode(request):
            from django.shortcuts import render
            return render(request, "maintenance.html")
        else:
            return self.get_response(request)

# }}}


def settings_context_processor(request):
    from django.conf import settings
    return {
        "student_sign_in_view": "relate-sign_in_choice",
        "relate_sign_in_by_email_enabled":
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED,
        "relate_registration_enabled":
        settings.RELATE_REGISTRATION_ENABLED,
        "relate_sign_in_by_exam_tickets_enabled":
        settings.RELATE_SIGN_IN_BY_EXAM_TICKETS_ENABLED,
        "relate_sign_in_by_saml2_enabled":
        settings.RELATE_SIGN_IN_BY_SAML2_ENABLED,
        "maintenance_mode": is_maintenance_mode(request),
        "site_announcement": getattr(settings, "RELATE_SITE_ANNOUNCEMENT", None),
        }


def as_local_time(dtm):
    # type: (datetime.datetime) -> datetime.datetime
    """Takes a timezone-aware datetime and applies the server timezone."""

    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return dtm.astimezone(tz)


def localize_datetime(dtm):
    # type: (datetime.datetime) -> datetime.datetime
    """Takes an timezone-naive datetime and applies the server timezone."""

    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return tz.localize(dtm)  # type: ignore


def local_now():
    # type: () -> datetime.datetime

    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return tz.localize(datetime.datetime.now())  # type: ignore


def format_datetime_local(datetime, format='DATETIME_FORMAT'):
    # type: (datetime.datetime, str) -> str
    """
    Format a datetime object to a localized string via python.

    Note: The datetime rendered in template is itself locale aware.
    A custom format must be defined in settings.py.
    When a custom format uses a same name with an existing built-in
    format, it will be overrided by built-in format if l10n
    is enabled.
    """

    from django.utils import formats
    from django.utils.dateformat import format as dformat

    try:
        return formats.date_format(datetime, format)
    except AttributeError:
        try:
            return dformat(datetime, format)
        except AttributeError:
            return formats.date_format(datetime, "DATETIME_FORMAT")


# {{{ dict_to_struct

class Struct(object):
    def __init__(self, entries):
        # type: (Dict) -> None
        for name, val in six.iteritems(entries):
            self.__dict__[name] = val

        self._field_names = list(six.iterkeys(entries))

    def __repr__(self):
        return repr(self.__dict__)


def dict_to_struct(data):
    # type: (Dict) -> Struct
    if isinstance(data, list):
        return [dict_to_struct(d) for d in data]
    elif isinstance(data, dict):
        return Struct({k: dict_to_struct(v) for k, v in six.iteritems(data)})
    else:
        return data


def struct_to_dict(data):
    # type: (Struct) -> Dict
    return dict(
            (name, val)
            for name, val in six.iteritems(data.__dict__)
            if not name.startswith("_"))

# }}}


def retry_transaction(f, args, kwargs={}, max_tries=None, serializable=None):
    # type: (Any, Tuple, Dict, Optional[int], Optional[bool]) -> Any

    from django.db import transaction
    from django.db.utils import OperationalError

    if max_tries is None:
        max_tries = 5
    if serializable is None:
        serializable = False

    assert max_tries > 0
    while True:
        try:
            with transaction.atomic():
                if serializable:
                    from django.db import connections, DEFAULT_DB_ALIAS
                    conn = connections[DEFAULT_DB_ALIAS]
                    if conn.vendor == "postgresql":
                        cursor = conn.cursor()
                        cursor.execute(
                                "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")

                return f(*args, **kwargs)
        except OperationalError:
            max_tries -= 1
            if not max_tries:
                raise

        from random import uniform
        from time import sleep
        sleep(uniform(0.05, 0.2))


class retry_transaction_decorator(object):  # noqa
    def __init__(self, max_tries=None, serializable=None):
        # type: (Optional[int], Optional[bool]) -> None
        self.max_tries = max_tries
        self.serializable = serializable

    def __call__(self, f):
        # type: (Any) -> Any
        from functools import update_wrapper

        def wrapper(*args, **kwargs):
            return retry_transaction(f, args, kwargs,
                    max_tries=self.max_tries,
                    serializable=self.serializable)

        update_wrapper(wrapper, f)
        return wrapper


# {{{ hang debugging

def dumpstacks(signal, frame):
    import threading
    import sys
    import traceback

    id2name = dict([(th.ident, th.name) for th in threading.enumerate()])
    code = []
    for threadId, stack in sys._current_frames().items():
        code.append("\n# Thread: %s(%d)" % (id2name.get(threadId, ""), threadId))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append("  %s" % (line.strip()))
    print("\n".join(code))


if 0:
    import signal
    import os
    print("*** HANG DUMP HANDLER ACTIVATED: 'kill -USR1 %s' to dump stacks"
            % os.getpid())
    signal.signal(signal.SIGUSR1, dumpstacks)

# }}}


# {{{ convert django language name to js styled language name

def to_js_lang_name(dj_lang_name):
    """
    Turns a django language name (en-us) into a js styled language
    name (en-US).
    """
    p = dj_lang_name.find('-')
    if p >= 0:
        return dj_lang_name[:p].lower() + '-' + dj_lang_name[p + 1:].upper()
    else:
        return dj_lang_name.lower()

# }}}


#{{{ Allow multiple email connections
# https://gist.github.com/niran/840999

def get_outbound_mail_connection(label=None, **kwargs):
    # type: (Optional[Text], **Any) -> Any
    from django.conf import settings
    if label is None:
        label = getattr(settings, 'EMAIL_CONNECTION_DEFAULT', None)

    try:
        connections = getattr(settings, 'EMAIL_CONNECTIONS')
        options = connections[label]
    except (KeyError, AttributeError):
        # Neither EMAIL_CONNECTIONS nor
        # EMAIL_CONNECTION_DEFAULT in
        # settings fail silently and fall
        # back to django's built-in
        # get_connection.
        options = {}

    options.update(kwargs)

    from django.core import mail
    return mail.get_connection(**options)

#}}}


def ignore_no_such_table(f, *args):
    from django.db import connections, DEFAULT_DB_ALIAS
    conn = connections[DEFAULT_DB_ALIAS]

    if conn.vendor == "postgresql":
        cursor = conn.cursor()
        cursor.execute("SAVEPOINT sp;")

    def local_rollback():
        if conn.vendor == "postgresql":
            cursor = conn.cursor()
            cursor.execute("ROLLBACK TO SAVEPOINT sp;")

    from django.db.utils import OperationalError, ProgrammingError
    try:
        return f(*args)

    # django.auth actually will not create auth_* if we're starting
    # with an empty database and a custom user model.

    except OperationalError as e:
        if "no such table" in str(e):
            local_rollback()
        else:
            raise

    except ProgrammingError as e:
        cause = getattr(e, "__cause__", None)
        pgcode = getattr(cause, "pgcode", None)
        if pgcode == "42P01":
            local_rollback()
        elif "no such table" in str(e):
            local_rollback()
        else:
            raise


# vim: foldmethod=marker
