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

import six
from django.conf import settings
from django.core.checks import Critical, Warning, register
from django.core.exceptions import ImproperlyConfigured

REQUIRED_CONF_ERROR_PATTERN = (
    "You must configure %(location)s for RELATE to run properly.")
INSTANCE_ERROR_PATTERN = "%(location)s must be an instance of %(types)s."
GENERIC_ERROR_PATTERN = "Error at %(location)s: %(error_type)s: %(error_str)s"

EMAIL_CONNECTIONS = "EMAIL_CONNECTIONS"
RELATE_BASE_URL = "RELATE_BASE_URL"
RELATE_EMAIL_APPELATION_PRIORITY_LIST = "RELATE_EMAIL_APPELATION_PRIORITY_LIST"
RELATE_FACILITIES = "RELATE_FACILITIES"
RELATE_MAINTENANCE_MODE_EXCEPTIONS = "RELATE_MAINTENANCE_MODE_EXCEPTIONS"
RELATE_SESSION_RESTART_COOLDOWN_SECONDS = "RELATE_SESSION_RESTART_COOLDOWN_SECONDS"
RELATE_TICKET_MINUTES_VALID_AFTER_USE = "RELATE_TICKET_MINUTES_VALID_AFTER_USE"
GIT_ROOT = "GIT_ROOT"
RELATE_STARTUP_CHECKS = "RELATE_STARTUP_CHECKS"
RELATE_STARTUP_CHECKS_EXTRA = "RELATE_STARTUP_CHECKS_EXTRA"

RELATE_STARTUP_CHECKS_TAG = "start_up_checks"
RELATE_STARTUP_CHECKS_EXTRA_TAG = "startup_checks_extra"

# {{{ for mypy

if False:
    from typing import Any  # noqa

# }}}


class RelateCriticalCheckMessage(Critical):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(RelateCriticalCheckMessage, self).__init__(*args, **kwargs)
        if not self.obj:  # type: ignore
            self.obj = ImproperlyConfigured  # type: Any


class DeprecatedException(Exception):
    pass


def get_ip_network(ip_range):
    import ipaddress
    return ipaddress.ip_network(six.text_type(ip_range))


def check_relate_settings(app_configs, **kwargs):
    errors = []

    # {{{ check RELATE_BASE_URL
    relate_base_url = getattr(settings, RELATE_BASE_URL, None)
    if relate_base_url is None:
        errors.append(RelateCriticalCheckMessage(
            msg=REQUIRED_CONF_ERROR_PATTERN % {"location": RELATE_BASE_URL},
            id="relate_base_url.E001"
        ))
    elif not isinstance(relate_base_url, str):
        errors.append(RelateCriticalCheckMessage(
            msg=(INSTANCE_ERROR_PATTERN
                 % {"location": RELATE_BASE_URL, "types": "str"}),
            id="relate_base_url.E002"
        ))
    elif not relate_base_url.strip():
        errors.append(RelateCriticalCheckMessage(
            msg="%(location)s should not be an empty string"
                % {"location": RELATE_BASE_URL},
            id="relate_base_url.E003"
        ))
    # }}}

    # {{{ check RELATE_EMAIL_APPELATION_PRIORITY_LIST
    relate_email_appelation_priority_list = getattr(
        settings, RELATE_EMAIL_APPELATION_PRIORITY_LIST, None)
    if relate_email_appelation_priority_list is not None:
        if not isinstance(relate_email_appelation_priority_list, (list, tuple)):
            errors.append(RelateCriticalCheckMessage(
                msg=(
                    INSTANCE_ERROR_PATTERN
                    % {"location": RELATE_EMAIL_APPELATION_PRIORITY_LIST,
                       "types": "list or tuple"}),
                id="relate_email_appelation_priority_list.E002")
            )
    # }}}

    # {{{ check EMAIL_CONNECTIONS
    email_connections = getattr(settings, EMAIL_CONNECTIONS, None)
    if email_connections is not None:
        if not isinstance(email_connections, dict):
            errors.append(RelateCriticalCheckMessage(
                msg=(
                    INSTANCE_ERROR_PATTERN
                    % {"location": EMAIL_CONNECTIONS,
                       "types": "dict"}),
                id="email_connections.E001"
            ))
        else:
            for label, c in six.iteritems(email_connections):
                if not isinstance(c, dict):
                    errors.append(RelateCriticalCheckMessage(
                        msg=(
                            INSTANCE_ERROR_PATTERN
                            % {"location": "'%s' in '%s'"
                                           % (label, EMAIL_CONNECTIONS),
                               "types": "dict"}),
                        id="email_connections.E002"
                    ))
                else:
                    if "backend" in c:
                        from django.utils.module_loading import import_string
                        try:
                            import_string(c["backend"])
                        except ImportError as e:
                            errors.append(RelateCriticalCheckMessage(
                                msg=(
                                    GENERIC_ERROR_PATTERN
                                    % {
                                        "location":
                                            "'%s' in %s"
                                            % (label, RELATE_FACILITIES),
                                        "error_type": type(e).__name__,
                                        "error_str": str(e)
                                    }),
                                id="email_connections.E003")
                            )
    # }}}

    # {{{ check RELATE_FACILITIES

    relate_facilities_conf = getattr(settings, RELATE_FACILITIES, None)
    if relate_facilities_conf is not None:
        from course.utils import get_facilities_config
        try:
            facilities = get_facilities_config()
        except Exception as e:
            errors.append(RelateCriticalCheckMessage(
                msg=(
                    GENERIC_ERROR_PATTERN
                    % {
                        "location": RELATE_FACILITIES,
                        "error_type": type(e).__name__,
                        "error_str": str(e)
                    }),
                id="relate_facilities.E001")
            )
        else:
            if not isinstance(facilities, dict):
                errors.append(RelateCriticalCheckMessage(
                    msg=(
                        "'%(location)s' must either be or return a dictionary"
                        % {"location": RELATE_FACILITIES}),
                    id="relate_facilities.E002")
                )
            else:
                for facility, conf in six.iteritems(facilities):
                    if not isinstance(conf, dict):
                        errors.append(RelateCriticalCheckMessage(
                            msg=(
                                INSTANCE_ERROR_PATTERN
                                % {"location":
                                       "Facility `%s` in %s"
                                       % (facility, RELATE_FACILITIES),
                                   "types": "dict"}),
                            id="relate_facilities.E003")
                        )
                    else:
                        ip_ranges = conf.get("ip_ranges", [])
                        if ip_ranges:
                            if not isinstance(ip_ranges, (list, tuple)):
                                errors.append(RelateCriticalCheckMessage(
                                    msg=(
                                        INSTANCE_ERROR_PATTERN
                                        % {"location":
                                               "'ip_ranges' in facility `%s` in %s"
                                               % (facilities, RELATE_FACILITIES),
                                           "types": "list or tuple"}),
                                    id="relate_facilities.E004")
                                )
                            else:
                                for ip_range in ip_ranges:
                                    try:
                                        get_ip_network(ip_range)
                                    except Exception as e:
                                        errors.append(RelateCriticalCheckMessage(
                                            msg=(
                                                GENERIC_ERROR_PATTERN
                                                % {
                                                    "location":
                                                        "'ip_ranges' in "
                                                        "facility `%s` in %s"
                                                        % (facility,
                                                           RELATE_FACILITIES),
                                                    "error_type": type(e).__name__,
                                                    "error_str": str(e)
                                                }),
                                            id="relate_facilities.E005")
                                        )
                        else:
                            if not callable(relate_facilities_conf):
                                errors.append(Warning(
                                    msg=(
                                        "Faclity `%s` in %s is an open facility "
                                        "as it has no configured `ip_ranges`"
                                        % (facility, RELATE_FACILITIES)
                                    ),
                                    id="relate_facilities.W001"
                                ))

    # }}}

    # {{{ check RELATE_MAINTENANCE_MODE_EXCEPTIONS
    relate_maintenance_mode_exceptions = getattr(
        settings, RELATE_MAINTENANCE_MODE_EXCEPTIONS, None)
    if relate_maintenance_mode_exceptions is not None:
        if not isinstance(relate_maintenance_mode_exceptions, (list, tuple)):
            errors.append(RelateCriticalCheckMessage(
                msg=(INSTANCE_ERROR_PATTERN
                     % {"location": RELATE_MAINTENANCE_MODE_EXCEPTIONS,
                        "types": "list or tuple"}),
                id="relate_maintenance_mode_exceptions.E001")
            )
        else:
            for ip in relate_maintenance_mode_exceptions:
                try:
                    get_ip_network(ip)
                except Exception as e:
                    errors.append(RelateCriticalCheckMessage(
                        msg=(
                            GENERIC_ERROR_PATTERN
                            % {"location":
                                   "ip/ip_ranges '%s' in %s"
                                   % (ip, RELATE_FACILITIES),
                               "error_type": type(e).__name__,
                               "error_str": str(e)
                               }),
                        id="relate_maintenance_mode_exceptions.E002")
                    )
    # }}}

    # {{{ check RELATE_SESSION_RESTART_COOLDOWN_SECONDS
    relate_session_restart_cooldown_seconds = getattr(
        settings, RELATE_SESSION_RESTART_COOLDOWN_SECONDS, None)
    if relate_session_restart_cooldown_seconds is not None:
        if not isinstance(relate_session_restart_cooldown_seconds, (int, float)):
            errors.append(RelateCriticalCheckMessage(
                msg=(INSTANCE_ERROR_PATTERN
                     % {"location": RELATE_SESSION_RESTART_COOLDOWN_SECONDS,
                        "types": "int or float"}),
                id="relate_session_restart_cooldown_seconds.E001")
            )
        else:
            if relate_session_restart_cooldown_seconds < 0:
                errors.append(RelateCriticalCheckMessage(
                    msg=(
                        "%(location)s must be a positive number, "
                        "got %(value)s instead"
                        % {"location": RELATE_SESSION_RESTART_COOLDOWN_SECONDS,
                           "value": relate_session_restart_cooldown_seconds}),
                    id="relate_session_restart_cooldown_seconds.E002")
                )

    # }}}

    # {{{ check RELATE_SESSION_RESTART_COOLDOWN_SECONDS
    relate_ticket_minutes_valid_after_use = getattr(
        settings, RELATE_TICKET_MINUTES_VALID_AFTER_USE, None)
    if relate_ticket_minutes_valid_after_use is not None:
        if not isinstance(relate_ticket_minutes_valid_after_use, (int, float)):
            errors.append(RelateCriticalCheckMessage(
                msg=(INSTANCE_ERROR_PATTERN
                     % {"location": RELATE_TICKET_MINUTES_VALID_AFTER_USE,
                        "types": "int or float"}),
                id="relate_ticket_minutes_valid_after_use.E001")
            )
        else:
            if relate_ticket_minutes_valid_after_use < 0:
                errors.append(RelateCriticalCheckMessage(
                    msg=(
                        "%(location)s must be a positive number, "
                        "got %(value)s instead"
                        % {"location": RELATE_TICKET_MINUTES_VALID_AFTER_USE,
                           "value": relate_ticket_minutes_valid_after_use}),
                    id="relate_ticket_minutes_valid_after_use.E002")
                )

    # }}}

    # {{{ check GIT_ROOT
    git_root = getattr(settings, GIT_ROOT, None)
    if git_root is None:
        errors.append(RelateCriticalCheckMessage(
            msg=REQUIRED_CONF_ERROR_PATTERN % {"location": GIT_ROOT},
            id="git_root.E001"
        ))
    elif not isinstance(git_root, str):
        errors.append(RelateCriticalCheckMessage(
            msg=INSTANCE_ERROR_PATTERN % {"location": GIT_ROOT, "types": "str"},
            id="git_root.E002"
        ))
    else:
        import os
        if not os.path.isdir(git_root):
            errors.append(RelateCriticalCheckMessage(
                msg=("`%(path)s` connfigured in %(location)s is not a valid path"
                     % {"path": git_root, "location": GIT_ROOT}),
                id="git_root.E003"
            ))
        else:
            if not os.access(git_root, os.W_OK):
                errors.append(RelateCriticalCheckMessage(
                    msg=("`%(path)s` connfigured in %(location)s is not writable "
                         "by RELATE"
                         % {"path": git_root, "location": GIT_ROOT}),
                    id="git_root.E004"
                ))
            if not os.access(git_root, os.R_OK):
                errors.append(RelateCriticalCheckMessage(
                    msg=("`%(path)s` connfigured in %(location)s is not readable "
                         "by RELATE"
                         % {"path": git_root, "location": GIT_ROOT}),
                    id="git_root.E005"
                ))

    # }}}

    return errors


def register_startup_checks():
    register(check_relate_settings, RELATE_STARTUP_CHECKS_TAG)


def register_startup_checks_extra():
    """
    Register extra checks provided by user.
    Here we will have to raise error for Exceptions, as that can not be done
    via check: all checks, including check_relate_settings, will only be
    executed after self.ready() is done.
    """
    startup_checks_extra = getattr(settings, RELATE_STARTUP_CHECKS_EXTRA, None)
    if startup_checks_extra:
        if not isinstance(startup_checks_extra, (list, tuple)):
            raise ImproperlyConfigured(
                INSTANCE_ERROR_PATTERN
                % {"location": RELATE_STARTUP_CHECKS_EXTRA,
                   "types": "list or tuple"
                   }
            )
        from django.utils.module_loading import import_string
        for c in startup_checks_extra:
            try:
                check_item = import_string(c)
            except Exception as e:
                raise ImproperlyConfigured(
                    GENERIC_ERROR_PATTERN
                    % {
                        "location": RELATE_STARTUP_CHECKS_EXTRA,
                        "error_type": type(e).__name__,
                        "error_str": str(e)
                    })
            else:
                register(check_item, RELATE_STARTUP_CHECKS_EXTRA_TAG)

# vim: foldmethod=marker
