from __future__ import annotations


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
from collections.abc import Iterable

from django.conf import settings
from django.core.checks import Critical, Warning, register
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


REQUIRED_CONF_ERROR_PATTERN = (
    "You must configure %(location)s for RELATE to run properly.")
INSTANCE_ERROR_PATTERN = "%(location)s must be an instance of %(types)s."
GENERIC_ERROR_PATTERN = "Error in '%(location)s': %(error_type)s: %(error_str)s"

USE_I18N = "USE_I18N"
LANGUAGES = "LANGUAGES"

RELATE_SITE_NAME = "RELATE_SITE_NAME"
RELATE_CUTOMIZED_SITE_NAME = "RELATE_CUTOMIZED_SITE_NAME"
RELATE_OVERRIDE_TEMPLATES_DIRS = "RELATE_OVERRIDE_TEMPLATES_DIRS"
EMAIL_CONNECTIONS = "EMAIL_CONNECTIONS"
RELATE_BASE_URL = "RELATE_BASE_URL"
RELATE_FACILITIES = "RELATE_FACILITIES"
RELATE_MAINTENANCE_MODE_EXCEPTIONS = "RELATE_MAINTENANCE_MODE_EXCEPTIONS"
RELATE_SESSION_RESTART_COOLDOWN_SECONDS = "RELATE_SESSION_RESTART_COOLDOWN_SECONDS"
RELATE_TICKET_MINUTES_VALID_AFTER_USE = "RELATE_TICKET_MINUTES_VALID_AFTER_USE"
GIT_ROOT = "GIT_ROOT"
RELATE_BULK_STORAGE = "RELATE_BULK_STORAGE"
RELATE_STARTUP_CHECKS = "RELATE_STARTUP_CHECKS"
RELATE_STARTUP_CHECKS_EXTRA = "RELATE_STARTUP_CHECKS_EXTRA"

RELATE_STARTUP_CHECKS_TAG = "start_up_check"
RELATE_STARTUP_CHECKS_EXTRA_TAG = "startup_checks_extra"
RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION = (
    "RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION")
RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE = (
    "RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE")


class RelateCriticalCheckMessage(Critical):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.obj = self.obj or ImproperlyConfigured.__name__


class DeprecatedException(Exception):
    pass


def get_ip_network(ip_range):
    import ipaddress
    return ipaddress.ip_network(str(ip_range))


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
            msg=f"{RELATE_BASE_URL} should not be an empty string",
            id="relate_base_url.E003"
        ))
    # }}}

    from accounts.utils import relate_user_method_settings

    # check RELATE_EMAIL_APPELLATION_PRIORITY_LIST
    errors.extend(
        relate_user_method_settings.check_email_appellation_priority_list())

    # check RELATE_CSV_SETTINGS
    errors.extend(relate_user_method_settings.check_custom_full_name_method())

    # check RELATE_USER_PROFILE_MASK_METHOD
    errors.extend(relate_user_method_settings.check_user_profile_mask_method())

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
            for label, c in email_connections.items():
                if not isinstance(c, dict):
                    errors.append(RelateCriticalCheckMessage(
                        msg=(
                            INSTANCE_ERROR_PATTERN
                            % {"location": f"'{label}' in '{EMAIL_CONNECTIONS}'",
                               "types": "dict"}),
                        id="email_connections.E002"
                    ))
                else:
                    if "backend" in c:
                        try:
                            import_string(c["backend"])
                        except ImportError as e:
                            errors.append(RelateCriticalCheckMessage(
                                msg=(
                                    GENERIC_ERROR_PATTERN
                                    % {
                                        "location":
                                            f"'{label}' in {RELATE_FACILITIES}",
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
                        f"'{RELATE_FACILITIES}' must either be or return a dictionary"),
                    id="relate_facilities.E002")
                )
            else:
                for facility, conf in facilities.items():
                    if not isinstance(conf, dict):
                        errors.append(RelateCriticalCheckMessage(
                            msg=(
                                INSTANCE_ERROR_PATTERN
                                % {"location":
                                       f"Facility `{facility}` in {RELATE_FACILITIES}",
                                   "types": "dict"}),
                            id="relate_facilities.E003")
                        )
                    else:
                        ip_ranges = conf.get("ip_ranges", [])
                        if ip_ranges:
                            if not isinstance(ip_ranges, list | tuple):
                                errors.append(RelateCriticalCheckMessage(
                                    msg=(
                                        INSTANCE_ERROR_PATTERN
                                        % {"location":
                                               f"'ip_ranges' in facility `{facilities}` in {RELATE_FACILITIES}",  # noqa: E501
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
                                                        f"facility `{facility}` in {RELATE_FACILITIES}",  # noqa: E501
                                                    "error_type": type(e).__name__,
                                                    "error_str": str(e)
                                                }),
                                            id="relate_facilities.E005")
                                        )
                        else:
                            if not callable(relate_facilities_conf):
                                errors.append(Warning(
                                    msg=(
                                        f"Faclity `{facility}` in {RELATE_FACILITIES} is an open facility "  # noqa: E501
                                        "as it has no configured `ip_ranges`"
                                    ),
                                    id="relate_facilities.W001"
                                ))

    # }}}

    # {{{ check RELATE_MAINTENANCE_MODE_EXCEPTIONS
    relate_maintenance_mode_exceptions = getattr(
        settings, RELATE_MAINTENANCE_MODE_EXCEPTIONS, None)
    if relate_maintenance_mode_exceptions is not None:
        if not isinstance(relate_maintenance_mode_exceptions, list | tuple):
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
                                   f"ip/ip_ranges '{ip}' in {RELATE_FACILITIES}",
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
        if not isinstance(relate_session_restart_cooldown_seconds, int | float):
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
                        f"{RELATE_SESSION_RESTART_COOLDOWN_SECONDS} must be a positive number, "  # noqa: E501
                        f"got {relate_session_restart_cooldown_seconds} instead"),
                    id="relate_session_restart_cooldown_seconds.E002")
                )

    # }}}

    # {{{ check RELATE_TICKET_MINUTES_VALID_AFTER_USE
    relate_ticket_minutes_valid_after_use = getattr(
        settings, RELATE_TICKET_MINUTES_VALID_AFTER_USE, None)
    if relate_ticket_minutes_valid_after_use is not None:
        if not isinstance(relate_ticket_minutes_valid_after_use, int | float):
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
                        f"{RELATE_TICKET_MINUTES_VALID_AFTER_USE} must be a positive number, "  # noqa: E501
                        f"got {relate_ticket_minutes_valid_after_use} instead"),
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
        if not os.path.isdir(git_root):
            errors.append(RelateCriticalCheckMessage(
                msg=(f"`{git_root}` configured in {GIT_ROOT} is not a valid path"),
                id="git_root.E003"
            ))
        else:
            if not os.access(git_root, os.W_OK):
                errors.append(RelateCriticalCheckMessage(
                    msg=(f"`{git_root}` configured in {GIT_ROOT} is not writable "
                         "by RELATE"),
                    id="git_root.E004"
                ))
            if not os.access(git_root, os.R_OK):
                errors.append(RelateCriticalCheckMessage(
                    msg=(f"`{git_root}` configured in {GIT_ROOT} is not readable "
                         "by RELATE"),
                    id="git_root.E005"
                ))

    # }}}

    # {{{ check RELATE_BULK_STORAGE

    bulk_storage = getattr(settings, RELATE_BULK_STORAGE, None)
    from django.core.files.storage import Storage
    if bulk_storage is None:
        errors.append(RelateCriticalCheckMessage(
            msg=REQUIRED_CONF_ERROR_PATTERN % {
                "location": RELATE_BULK_STORAGE},
            id="bulk_storage.E001"
        ))
    elif not isinstance(bulk_storage, Storage):
        errors.append(RelateCriticalCheckMessage(
            msg=INSTANCE_ERROR_PATTERN % {
                "location": RELATE_BULK_STORAGE, "types": "Storage"},
            id="bulk_storage.E002"
        ))

    # }}}

    # {{{ check RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION
    relate_disable_codehilite_markdown_extension = getattr(
        settings, RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION, None)
    if relate_disable_codehilite_markdown_extension is not None:
        if not isinstance(relate_disable_codehilite_markdown_extension, bool):
            errors.append(
                Warning(
                    msg=f"{RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION} is not a Boolean value: `{relate_disable_codehilite_markdown_extension!r}`, "  # noqa: E501
                        "assuming True",
                    id="relate_disable_codehilite_markdown_extension.W001"))
        elif not relate_disable_codehilite_markdown_extension:
            errors.append(
                Warning(
                    msg="%(location)s is set to False "
                        "(with 'markdown.extensions.codehilite' enabled'), "
                        "noticing that some pages with code fence markdown "
                        "might crash"
                        % {"location":
                               RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION,
                           },
                    id="relate_disable_codehilite_markdown_extension.W002"))

    # }}}

    # {{{ check LANGUAGES, why this is not done in django?

    languages = settings.LANGUAGES

    if (isinstance(languages, str)
            or not isinstance(languages, Iterable)):
        errors.append(RelateCriticalCheckMessage(
            msg=(INSTANCE_ERROR_PATTERN
                 % {"location": LANGUAGES,
                    "types": "an iterable (e.g., a list or tuple)."}),
            id="relate_languages.E001")
        )
    else:
        if any(isinstance(choice, str)
                       or not isinstance(choice, Iterable) or len(choice) != 2
               for choice in languages):
            errors.append(RelateCriticalCheckMessage(
                msg=(f"'{LANGUAGES}' must be an iterable containing "
                     "(language code, language description) tuples, just "
                     "like the format of LANGUAGES setting ("
                     "https://docs.djangoproject.com/en/dev/ref/settings/"
                     "#languages)"),
                id="relate_languages.E002")
            )
        else:
            from collections import OrderedDict
            options_dict = OrderedDict(tuple(settings.LANGUAGES))
            all_lang_codes = [lang_code for lang_code, lang_descr
                              in tuple(settings.LANGUAGES)]
            for lang_code in options_dict.keys():
                if all_lang_codes.count(lang_code) > 1:
                    errors.append(Warning(
                        msg=(
                            "Duplicate language entries were found in "
                            f"settings.LANGUAGES for '{lang_code}', '{options_dict[lang_code]}' will be used "  # noqa: E501
                            "as its language_description"),
                        id="relate_languages.W001"
                    ))

    # }}}

    # {{{ check RELATE_SITE_NAME
    try:
        site_name = settings.RELATE_SITE_NAME
        if site_name is None:
            errors.append(
                RelateCriticalCheckMessage(
                    msg=(f"{RELATE_SITE_NAME} must not be None"),
                    id="relate_site_name.E002")
            )
        else:
            if not isinstance(site_name, str):
                errors.append(RelateCriticalCheckMessage(
                    msg=(INSTANCE_ERROR_PATTERN
                         % {"location": f"{RELATE_SITE_NAME}/{RELATE_CUTOMIZED_SITE_NAME}",  # noqa: E501
                            "types": "string"}),
                    id="relate_site_name.E003"))
            elif not site_name.strip():
                errors.append(RelateCriticalCheckMessage(
                    msg=(f"{RELATE_SITE_NAME} must not be an empty string"),
                    id="relate_site_name.E004"))
    except AttributeError:
        # This happens when RELATE_SITE_NAME is DELETED from settings.
        errors.append(
            RelateCriticalCheckMessage(
                msg=(REQUIRED_CONF_ERROR_PATTERN
                     % {"location": RELATE_SITE_NAME}),
                id="relate_site_name.E001")
        )
    # }}}

    # {{{ check RELATE_OVERRIDE_TEMPLATES_DIRS

    relate_override_templates_dirs = getattr(settings,
                                             RELATE_OVERRIDE_TEMPLATES_DIRS, None)
    if relate_override_templates_dirs is not None:
        if (isinstance(relate_override_templates_dirs, str)
                or not isinstance(relate_override_templates_dirs, Iterable)):
            errors.append(RelateCriticalCheckMessage(
                msg=(INSTANCE_ERROR_PATTERN
                     % {"location": RELATE_OVERRIDE_TEMPLATES_DIRS,
                        "types": "an iterable (e.g., a list or tuple)."}),
                id="relate_override_templates_dirs.E001"))
        else:
            if any(not isinstance(directory, str)
                   for directory in relate_override_templates_dirs):
                errors.append(RelateCriticalCheckMessage(
                    msg=(f"'{RELATE_OVERRIDE_TEMPLATES_DIRS}' must contain only string of paths."),  # noqa: E501
                    id="relate_override_templates_dirs.E002"))
            else:
                for directory in relate_override_templates_dirs:
                    if not os.path.isdir(directory):
                        errors.append(
                            Warning(
                                msg=(
                                    f"Invalid Templates Dirs item '{directory}' in '{RELATE_OVERRIDE_TEMPLATES_DIRS}', "  # noqa: E501
                                    "it will be ignored."),
                                id="relate_override_templates_dirs.W001"
                            ))

    # }}}

    # {{{ check RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE
    relate_custom_page_types_removed_deadline = getattr(
        settings, RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE, None)
    if relate_custom_page_types_removed_deadline is not None:
        from datetime import datetime
        if not isinstance(relate_custom_page_types_removed_deadline, datetime):
            errors.append(RelateCriticalCheckMessage(
                msg=(INSTANCE_ERROR_PATTERN
                     % {"location": RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE,
                        "types": "datetime.datetime"}),
                id="relate_custom_page_types_removed_deadline.E001"))

    # }}}
    return errors


def register_startup_checks():
    register(check_relate_settings, RELATE_STARTUP_CHECKS_TAG)


def register_startup_checks_extra():
    """
    Register extra checks provided by user.
    Here we will have to raise error for Exceptions, as that can not be done
    via check: all checks, including check_relate_settings, will only be
    executed after AppConfig.ready() is done.
    """
    startup_checks_extra = getattr(settings, RELATE_STARTUP_CHECKS_EXTRA, None)
    if startup_checks_extra is not None:
        if not isinstance(startup_checks_extra, list | tuple):
            raise ImproperlyConfigured(
                INSTANCE_ERROR_PATTERN
                % {"location": RELATE_STARTUP_CHECKS_EXTRA,
                   "types": "list or tuple"
                   }
            )
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
