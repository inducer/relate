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
from django.core.checks import Warning
from django.utils.functional import cached_property
from django.utils.module_loading import import_string

RELATE_USER_FULL_NAME_FORMAT_METHOD = "RELATE_USER_FULL_NAME_FORMAT_METHOD"


class RelateUserMethodSettingsInitializer(object):
    """
    This is used to check (validate) settings.RELATE_CSV_SETTINGS (optional)
    and initialize the settings for csv export for csv-related forms.
    """

    def __init__(self):
        self._custom_full_name_method = None

    @cached_property
    def get_custom_full_name_method(self):
        self.check_custom_full_name_method()
        return self._custom_full_name_method

    def check_custom_full_name_method(self):
        errors = []

        from django.conf import settings
        relate_user_full_name_format_method = getattr(
            settings, RELATE_USER_FULL_NAME_FORMAT_METHOD, None)
        self._custom_full_name_method = None
        if relate_user_full_name_format_method is not None:
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
