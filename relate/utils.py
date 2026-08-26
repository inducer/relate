from __future__ import annotations


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


import atexit
import datetime
import multiprocessing
import multiprocessing.connection
import threading
import time
from abc import ABC
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import (
    TYPE_CHECKING,
    Any,
    ParamSpec,
    TypeVar,
)
from zoneinfo import ZoneInfo

from django import forms
from django.http import HttpRequest
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from typing_extensions import Sentinel, TypeIs, deprecated, override


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping
    from pathlib import Path

    from django.contrib.auth.models import AbstractUser, AnonymousUser

    from accounts.models import User


T = TypeVar("T")
ResultT = TypeVar("ResultT")
P = ParamSpec("P")


class RelateHttpRequest(HttpRequest, ABC):
    # add monkey-patched request attributes

    # added by FacilityFindingMiddleware
    relate_facilities: Collection[str]

    # added by ExamLockdownMiddleware
    relate_exam_lockdown: bool

    relate_impersonate_original_user: User


def is_authed(user: AbstractUser | AnonymousUser | User) -> TypeIs[User]:
    return user.is_authenticated


@deprecated("use pytools.not_none")
def not_none(obj: T | None) -> T:
    assert obj is not None
    return obj


def string_concat(*strings: Any) -> str:
    return format_lazy("{}" * len(strings), *strings)  # type: ignore[return-value]


class StyledFormBase(forms.Form):
    def __init__(self, *args, **kwargs) -> None:
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self._configure_helper()
        super().__init__(*args, **kwargs)

    def _configure_helper(self) -> None:
        raise NotImplementedError


class StyledVerticalForm(StyledFormBase):
    @override
    def _configure_helper(self) -> None:
        pass


class StyledForm(StyledFormBase):
    @override
    def _configure_helper(self) -> None:
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs) -> None:

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super().__init__(*args, **kwargs)


def remote_address_from_request(request: HttpRequest) -> IPv4Address | IPv6Address:
    return ip_address(str(request.META["REMOTE_ADDR"]))


# {{{ maintenance mode

def is_maintenance_mode(request: HttpRequest):
    from django.conf import settings
    maintenance_mode = getattr(settings, "RELATE_MAINTENANCE_MODE", False)

    if maintenance_mode:
        exceptions = getattr(settings, "RELATE_MAINTENANCE_MODE_EXCEPTIONS", [])

        remote_address = remote_address_from_request(request)

        for exc in exceptions:
            if remote_address in ip_network(str(exc)):
                maintenance_mode = False
                break

    return maintenance_mode


class MaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_maintenance_mode(request):
            from django.shortcuts import render
            return render(request, "maintenance.html")
        else:
            return self.get_response(request)

# }}}


def get_site_name() -> str:
    from django.conf import settings
    return getattr(settings, "RELATE_SITE_NAME", "RELATE")


def render_email_template(
            template_name: str,
            context: Mapping[str, Any] | None = None,
            request: HttpRequest | None = None,
            using: str | None = None
        ) -> str:
    if context is None:
        context = {}
    context = dict(context)
    context.update({"relate_site_name": _(get_site_name())})
    from django.template.loader import render_to_string
    return render_to_string(template_name, context, request, using)


def settings_context_processor(request):
    from django.conf import settings
    return {
        "student_sign_in_view": "relate-sign_in_choice",
        "relate_sign_in_by_email_enabled":
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED,
        "relate_sign_in_by_username_enabled":
        settings.RELATE_SIGN_IN_BY_USERNAME_ENABLED,
        "relate_registration_enabled":
        settings.RELATE_REGISTRATION_ENABLED,
        "relate_sign_in_by_exam_tickets_enabled":
        settings.RELATE_SIGN_IN_BY_EXAM_TICKETS_ENABLED,
        "relate_sign_in_by_saml2_enabled":
        settings.RELATE_SIGN_IN_BY_SAML2_ENABLED,
        "maintenance_mode": is_maintenance_mode(request),
        "site_announcement": getattr(settings, "RELATE_SITE_ANNOUNCEMENT", None),
        "relate_site_name": _(get_site_name())
        }


def as_local_time(dtm: datetime.datetime) -> datetime.datetime:
    """Takes a timezone-aware datetime and applies the server timezone."""

    from django.conf import settings
    tz = ZoneInfo(settings.TIME_ZONE)
    return dtm.astimezone(tz)


def localize_datetime(dtm: datetime.datetime) -> datetime.datetime:
    """Takes an timezone-naive datetime and applies the server timezone."""

    assert dtm.tzinfo is None

    from django.conf import settings
    tz = ZoneInfo(settings.TIME_ZONE)
    return dtm.replace(tzinfo=tz)


def local_now() -> datetime.datetime:
    from django.conf import settings
    tz = ZoneInfo(settings.TIME_ZONE)
    return datetime.datetime.now(tz)


def format_datetime_local(
        datetime: datetime.datetime, format: str = "DATETIME_FORMAT") -> str:
    """
    Format a datetime object to a localized string via python.

    Note: The datetime rendered in template is itself locale aware.
    A custom format must be defined in settings.py.
    When a custom format uses a same name with an existing built-in
    format, it will be overridden by built-in format if l10n
    is enabled.
    """

    from django.utils import formats
    try:
        return formats.date_format(datetime, format)
    except AttributeError:
        try:
            from django.utils.dateformat import format as dformat
            return dformat(datetime, format)
        except AttributeError:
            return formats.date_format(datetime, "DATETIME_FORMAT")


def _retry_transaction(
            f: Callable[P, ResultT],
            max_tries: int | None,
            serializable: bool | None,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> ResultT:
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
                    from django.db import DEFAULT_DB_ALIAS, connections
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


class retry_transaction_decorator:  # ruff:ignore[invalid-class-name]
    def __init__(self, max_tries: int | None = None,
            serializable: bool | None = None) -> None:
        self.max_tries: int | None = max_tries
        self.serializable: bool | None = serializable

    def __call__(self, f: Callable[P, ResultT]) -> Callable[P, ResultT]:
        from functools import update_wrapper

        def wrapper(*args: P.args, **kwargs: P.kwargs):
            return _retry_transaction(f,
                    self.max_tries,
                    self.serializable,
                    *args,
                    **kwargs,
                    )

        update_wrapper(wrapper, f)
        return wrapper


# {{{ call with timeout

TIMED_OUT = Sentinel("TIMED_OUT")


@dataclass(frozen=True)
class _RaisedException:
    exc_value: Exception


# 'spawn' avoids inheriting the WSGI process's database connections.
MP_CONTEXT = multiprocessing.get_context("spawn")


def _call_with_timeout_worker(
            conn: multiprocessing.connection.Connection,
        ) -> None:
    from django.db import connections
    connections.close_all()

    try:
        while True:
            job = conn.recv()
            if job is None:
                return

            f, args, kwargs = job
            try:
                conn.send(f(*args, **kwargs))
            except Exception as exc:
                conn.send(_RaisedException(exc))
    except EOFError:
        pass
    finally:
        conn.close()


_WORKER_CONNECTION_CLOSED = object()


class _TimeoutWorker:
    def __init__(self) -> None:
        self.conn: Any | None = None
        self.process: Any | None = None
        self.result: Any = _WORKER_CONNECTION_CLOSED
        self.result_ready: threading.Event = threading.Event()
        self.receiver: threading.Thread | None = None

    def _receive_results(
                self, conn: multiprocessing.connection.Connection) -> None:
        while True:
            try:
                self.result = conn.recv()
            except (EOFError, OSError):
                self.result = _WORKER_CONNECTION_CLOSED
                self.result_ready.set()
                return
            else:
                self.result_ready.set()

    def start(self) -> None:
        parent_conn, child_conn = MP_CONTEXT.Pipe()
        process = MP_CONTEXT.Process(
                target=_call_with_timeout_worker,
                args=(child_conn,),
                daemon=True)
        process.start()
        child_conn.close()
        self.conn = parent_conn
        self.process = process
        self.receiver = threading.Thread(
                target=self._receive_results, args=(parent_conn,), daemon=True)
        self.receiver.start()

    def is_alive(self) -> bool:
        return (
                self.conn is not None
                and self.process is not None
                and self.process.is_alive())

    def dispatch(self, job: tuple[Any, tuple[Any, ...], dict[str, Any]]) -> None:
        assert self.conn is not None
        self.result = _WORKER_CONNECTION_CLOSED
        self.result_ready.clear()
        self.conn.send(job)

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
            self.conn.close()
            self.conn = None

        if self.process is not None:
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process = None

    def kill(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

        if self.process is not None:
            if self.process.is_alive():
                self.process.kill()
            self.process.join()
            self.process = None


_timeout_worker_local = threading.local()
_timeout_workers: set[_TimeoutWorker] = set()
_timeout_workers_lock = threading.Lock()


def _get_timeout_worker() -> _TimeoutWorker:
    worker = getattr(_timeout_worker_local, "worker", None)
    if worker is not None and worker.is_alive():
        return worker

    if worker is not None:
        worker.close()
        with _timeout_workers_lock:
            _timeout_workers.discard(worker)

    worker = _TimeoutWorker()
    worker.start()
    _timeout_worker_local.worker = worker
    with _timeout_workers_lock:
        _timeout_workers.add(worker)
    return worker


def _discard_timeout_worker(worker: _TimeoutWorker) -> None:
    worker.kill()
    if getattr(_timeout_worker_local, "worker", None) is worker:
        del _timeout_worker_local.worker
    with _timeout_workers_lock:
        _timeout_workers.discard(worker)


def _close_timeout_workers() -> None:
    with _timeout_workers_lock:
        workers = list(_timeout_workers)
        _timeout_workers.clear()

    for worker in workers:
        worker.close()


atexit.register(_close_timeout_workers)


def call_with_timeout(
            timeout: int,
            f: Callable[P, ResultT],
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> ResultT | TIMED_OUT:  # type: ignore[valid-type]
    """Call *f* in a thread-local worker process.

    The timeout covers worker creation, dispatch, and waiting for the result.
    A worker that does not finish before the deadline is killed and replaced on
    the next call from this thread. Worker startup and argument serialization
    are synchronous and cannot be forcibly interrupted. The callable,
    arguments, result, and any raised exception must be pickleable. Workers use
    the ``spawn`` start method and close Django connections before accepting
    jobs.
    """
    deadline = time.monotonic() + timeout
    if timeout <= 0:
        return TIMED_OUT

    worker = _get_timeout_worker()
    if time.monotonic() >= deadline:
        _discard_timeout_worker(worker)
        return TIMED_OUT

    try:
        worker.dispatch((f, args, kwargs))
        remaining = deadline - time.monotonic()
        if remaining > 0 and worker.result_ready.wait(remaining):
            result = worker.result
            if isinstance(result, _RaisedException):
                raise result.exc_value
            if result is not _WORKER_CONNECTION_CLOSED:
                return result
    except (BrokenPipeError, EOFError, OSError):
        pass

    _discard_timeout_worker(worker)
    return TIMED_OUT

# }}}


# {{{ hang debugging

def dumpstacks(signal, frame):  # pragma: no cover
    import sys
    import threading
    import traceback

    id2name = {th.ident: th.name for th in threading.enumerate()}
    code = []
    for thread_id, stack in sys._current_frames().items():
        code.append("\n# Thread: %s(%d)" % (id2name.get(thread_id, ""), thread_id))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append(f"  {line.strip()}")
    print("\n".join(code))


if 0:
    import os
    import signal
    print(f"*** HANG DUMP HANDLER ACTIVATED: 'kill -USR1 {os.getpid()}' to dump stacks")
    signal.signal(signal.SIGUSR1, dumpstacks)

# }}}


# {{{ Allow multiple email connections
# https://gist.github.com/niran/840999

def get_outbound_mail_connection(label: str | None = None, **kwargs: Any) -> Any:
    from django.conf import settings
    if label is None:
        label = getattr(settings, "EMAIL_CONNECTION_DEFAULT", None)

    try:
        connections = settings.EMAIL_CONNECTIONS  # type: ignore[misc]
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

# }}}


def ignore_no_such_table(f, *args):
    from django.db import DEFAULT_DB_ALIAS, connections
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
        if pgcode == "42P01" or "no such table" in str(e):
            local_rollback()
        else:
            raise


def force_remove_path(path: Path | str) -> None:
    """
    Work around deleting read-only path on Windows.
    Ref: https://docs.python.org/3.5/library/shutil.html#rmtree-example
    """
    import os
    import shutil
    import stat

    def remove_readonly(func: Callable[[Path | str], None], path: Path | str, _):
        """Clear the readonly bit and reattempt the removal"""
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(path, onerror=remove_readonly)


# {{{ date/datetime input

HTML5_DATE_FORMAT = "%Y-%m-%d"
HTML5_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


class HTML5DateInput(forms.DateInput):
    def __init__(self) -> None:
        super().__init__(
                attrs={"type": "date"},
                format=HTML5_DATE_FORMAT)


class HTML5DateTimeInput(forms.DateTimeInput):
    def __init__(self) -> None:
        super().__init__(
                attrs={"type": "datetime-local"},
                format=HTML5_DATETIME_FORMAT)

# }}}


# vim: foldmethod=marker
