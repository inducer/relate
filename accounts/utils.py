# -*- coding: utf-8 -*-

from __future__ import division, unicode_literals

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

import six
from django.utils.functional import cached_property
from django.utils.module_loading import import_string

from relate.checks import (
    INSTANCE_ERROR_PATTERN, Warning, RelateCriticalCheckMessage)
from course.constants import DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST

RELATE_USER_FULL_NAME_FORMAT_METHOD = "RELATE_USER_FULL_NAME_FORMAT_METHOD"
RELATE_EMAIL_APPELLATION_PRIORITY_LIST = (
    "RELATE_EMAIL_APPELLATION_PRIORITY_LIST")
RELATE_USER_PROFILE_MASK_METHOD = "RELATE_USER_PROFILE_MASK_METHOD"


class RelateUserMethodSettingsInitializer(object):
    """
    This is used to check (validate) settings.RELATE_CSV_SETTINGS (optional)
    and initialize the settings for csv export for csv-related forms.
    """

    def __init__(self):
        self._custom_full_name_method = None
        self._email_appellation_priority_list = (
                DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST)
        self._custom_profile_mask_method = None

    @cached_property
    def custom_full_name_method(self):
        self.check_custom_full_name_method()
        return self._custom_full_name_method

    @cached_property
    def email_appellation_priority_list(self):
        self.check_email_appellation_priority_list()
        return self._email_appellation_priority_list

    @cached_property
    def custom_profile_mask_method(self):
        self.check_user_profile_mask_method()
        return self._custom_profile_mask_method

    def check_user_profile_mask_method(self):
        self._custom_profile_mask_method = None
        errors = []

        from django.conf import settings
        custom_user_profile_mask_method = getattr(
            settings, RELATE_USER_PROFILE_MASK_METHOD, None)

        if custom_user_profile_mask_method is None:
            return errors

        if isinstance(custom_user_profile_mask_method, six.string_types):
            try:
                custom_user_profile_mask_method = (
                    import_string(custom_user_profile_mask_method))
            except ImportError:
                errors = [RelateCriticalCheckMessage(
                    msg=(
                            "%(location)s: `%(method)s` failed to be imported. "
                            % {"location": RELATE_USER_PROFILE_MASK_METHOD,
                               "method": custom_user_profile_mask_method
                               }
                    ),
                    id="relate_user_profile_mask_method.E001"
                )]
                return errors

        self._custom_profile_mask_method = custom_user_profile_mask_method
        if not callable(custom_user_profile_mask_method):
            errors.append(RelateCriticalCheckMessage(
                msg=(
                        "%(location)s: `%(method)s` is not a callable. "
                        % {"location": RELATE_USER_PROFILE_MASK_METHOD,
                           "method": custom_user_profile_mask_method
                           }
                ),
                id="relate_user_profile_mask_method.E002"
            ))
        else:
            import inspect
            if six.PY3:
                sig = inspect.signature(custom_user_profile_mask_method)
                n_args = len([p.name for p in sig.parameters.values()])
            else:
                # Don't count the number of defaults.
                # (getargspec returns args, varargs, varkw, defaults)
                n_args = sum(
                    [len(arg) for arg
                     in inspect.getargspec(custom_user_profile_mask_method)[:3]
                     if arg is not None])

            if not n_args or n_args > 1:
                errors.append(RelateCriticalCheckMessage(
                    msg=(
                        "%(location)s: `%(method)s` should have exactly "
                        "one arg, got %(n)d."
                        % {"location": RELATE_USER_PROFILE_MASK_METHOD,
                           "method": custom_user_profile_mask_method,
                           "n": n_args
                           }
                    ),
                    id="relate_user_profile_mask_method.E003"
                ))

        if errors:
            self._custom_profile_mask_method = None

        return errors

    def check_email_appellation_priority_list(self):
        errors = []
        self._email_appellation_priority_list = (
            DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST)

        from django.conf import settings
        custom_email_appellation_priority_list = getattr(
            settings, RELATE_EMAIL_APPELLATION_PRIORITY_LIST, None)
        if not custom_email_appellation_priority_list:
            if hasattr(settings, "RELATE_EMAIL_APPELATION_PRIORITY_LIST"):
                if settings.RELATE_EMAIL_APPELATION_PRIORITY_LIST is not None:
                    errors.append(Warning(
                        msg=("'RELATE_EMAIL_APPELATION_PRIORITY_LIST' is "
                             "deprecated due to typo, use "
                             "'RELATE_EMAIL_APPELLATION_PRIORITY_LIST' "
                             "instead."),
                        id="relate_email_appellation_priority_list.W003"))
                    custom_email_appellation_priority_list = (
                        settings.RELATE_EMAIL_APPELATION_PRIORITY_LIST)
        if not custom_email_appellation_priority_list:
            return errors

        if not isinstance(custom_email_appellation_priority_list, (list, tuple)):
            errors.append(Warning(
                msg=("%s, %s" % (
                        INSTANCE_ERROR_PATTERN
                        % {"location": RELATE_EMAIL_APPELLATION_PRIORITY_LIST,
                           "types": "list or tuple"},
                        "default value '%s' will be used"
                        % repr(DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST))),
                id="relate_email_appellation_priority_list.W001"))
            return errors

        priority_list = []
        not_supported_appels = []

        # filter out not allowd appellations in customized list
        for appell in custom_email_appellation_priority_list:
            if appell in DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST:
                priority_list.append(appell)
            else:
                not_supported_appels.append(appell)

        # make sure the default appellations are included in case
        # user defined appellations are not available.
        for appell in DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST:
            if appell not in priority_list:
                priority_list.append(appell)

        assert len(priority_list)
        self._email_appellation_priority_list = priority_list

        if not_supported_appels:
            errors.append(Warning(
                msg=("%(location)s: not supported email appelation(s) found "
                     "and will be ignored: %(not_supported_appelds)s. "
                     "%(actual)s will be used as "
                     "relate_email_appellation_priority_list."
                     % {"location": RELATE_EMAIL_APPELLATION_PRIORITY_LIST,
                        "not_supported_appelds": ", ".join(not_supported_appels),
                        "actual": repr(priority_list)}),
                id="relate_email_appellation_priority_list.W002"))
        return errors

    def check_custom_full_name_method(self):
        self._custom_full_name_method = None
        errors = []

        from django.conf import settings
        relate_user_full_name_format_method = getattr(
            settings, RELATE_USER_FULL_NAME_FORMAT_METHOD, None)

        if relate_user_full_name_format_method is None:
            return errors

        if isinstance(relate_user_full_name_format_method, six.string_types):
            try:
                relate_user_full_name_format_method = (
                    import_string(relate_user_full_name_format_method))
            except ImportError:
                errors = [Warning(
                    msg=(
                            "%(location)s: `%(method)s` failed to be imported, "
                            "default format method will be used."
                            % {"location": RELATE_USER_FULL_NAME_FORMAT_METHOD,
                               "method": relate_user_full_name_format_method
                               }
                    ),
                    id="relate_user_full_name_format_method.W001"
                )]
                return errors

        self._custom_full_name_method = relate_user_full_name_format_method
        if not callable(relate_user_full_name_format_method):
            errors.append(Warning(
                msg=(
                        "%(location)s: `%(method)s` is not a callable, "
                        "default format method will be used."
                        % {"location": RELATE_USER_FULL_NAME_FORMAT_METHOD,
                           "method": relate_user_full_name_format_method
                           }
                ),
                id="relate_user_full_name_format_method.W002"
            ))
        else:
            try:
                returned_name = (
                    relate_user_full_name_format_method("first_name",
                                                        "last_name"))
            except Exception as e:
                from traceback import format_exc
                errors.append(Warning(
                    msg=(
                            "%(location)s: `%(method)s` called with '"
                            "args 'first_name', 'last_name' failed with"
                            "exception below:\n"
                            "%(err_type)s: %(err_str)s\n"
                            "%(format_exc)s\n\n"
                            "Default format method will be used."
                            % {"location": RELATE_USER_FULL_NAME_FORMAT_METHOD,
                               "method": relate_user_full_name_format_method,
                               "err_type": type(e).__name__,
                               "err_str": str(e),
                               'format_exc': format_exc()}
                    ),
                    id="relate_user_full_name_format_method.W003"
                ))
            else:
                unexpected_return_value = ""
                if returned_name is None:
                    unexpected_return_value = "None"
                if not isinstance(returned_name, six.string_types):
                    unexpected_return_value = type(returned_name).__name__
                elif not returned_name.strip():
                    unexpected_return_value = "empty string %s" % returned_name
                if unexpected_return_value:
                    errors.append(Warning(
                        msg=("%(location)s: `%(method)s` is expected to "
                             "return a non-empty string, got `%(result)s`, "
                             "default format method will be used."
                             % {
                                 "location": RELATE_USER_FULL_NAME_FORMAT_METHOD,
                                 "method": relate_user_full_name_format_method,
                                 "result": unexpected_return_value,
                             }),
                        id="relate_user_full_name_format_method.W004"
                    ))
                else:
                    returned_name2 = (
                        relate_user_full_name_format_method("first_name2",
                                                            "last_name2"))
                    if returned_name == returned_name2:
                        errors.append(Warning(
                            msg=("%(location)s: `%(method)s` is expected to "
                                 "return different value with different "
                                 "input, default format method will be used."
                                 % {
                                     "location":
                                         RELATE_USER_FULL_NAME_FORMAT_METHOD,
                                     "method":
                                         relate_user_full_name_format_method
                                 }),
                            id="relate_user_full_name_format_method.W005"
                        ))

        if errors:
            self._custom_full_name_method = None

        return errors


relate_user_method_settings = RelateUserMethodSettingsInitializer()
