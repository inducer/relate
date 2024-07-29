from __future__ import annotations


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

from django.utils.functional import cached_property
from django.utils.module_loading import import_string

from course.constants import DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST
from relate.checks import INSTANCE_ERROR_PATTERN, RelateCriticalCheckMessage, Warning


RELATE_USER_FULL_NAME_FORMAT_METHOD = "RELATE_USER_FULL_NAME_FORMAT_METHOD"
RELATE_EMAIL_APPELLATION_PRIORITY_LIST = (
    "RELATE_EMAIL_APPELLATION_PRIORITY_LIST")
RELATE_USER_PROFILE_MASK_METHOD = "RELATE_USER_PROFILE_MASK_METHOD"


class RelateUserMethodSettingsInitializer:
    """
    This is used to check (validate) settings.RELATE_CSV_SETTINGS (optional)
    and initialize the settings for csv export for csv-related forms.
    """

    def __init__(self) -> None:
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

        if isinstance(custom_user_profile_mask_method, str):
            try:
                custom_user_profile_mask_method = (
                    import_string(custom_user_profile_mask_method))
            except ImportError:
                errors = [RelateCriticalCheckMessage(
                    msg=(
                        f"{RELATE_USER_PROFILE_MASK_METHOD}: "
                        f"`{custom_user_profile_mask_method}` failed to be imported. "
                    ),
                    id="relate_user_profile_mask_method.E001"
                )]
                return errors

        self._custom_profile_mask_method = custom_user_profile_mask_method
        if not callable(custom_user_profile_mask_method):
            errors.append(RelateCriticalCheckMessage(
                msg=(
                        f"{RELATE_USER_PROFILE_MASK_METHOD}: "
                        f"`{custom_user_profile_mask_method}` is not a callable."
                ),
                id="relate_user_profile_mask_method.E002"
            ))
        else:
            import inspect
            sig = inspect.signature(custom_user_profile_mask_method)
            n_args = len([p.name for p in sig.parameters.values()])

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

        if not isinstance(custom_email_appellation_priority_list, list | tuple):
            errors.append(Warning(
                msg=("{}, {}".format(
                        INSTANCE_ERROR_PATTERN
                        % {"location": RELATE_EMAIL_APPELLATION_PRIORITY_LIST,
                           "types": "list or tuple"},
                        f"default value '{DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST!r}' "
                        "will be used")),
                id="relate_email_appellation_priority_list.W001"))
            return errors

        priority_list = []
        not_supported_appels = []

        # filter out not allowed appellations in customized list
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
                msg=("{location}: not supported email appelation(s) found "
                     "and will be ignored: {not_supported_appelds}. "
                     "{actual} will be used as "
                     "relate_email_appellation_priority_list.".format(
                        location=RELATE_EMAIL_APPELLATION_PRIORITY_LIST,
                        not_supported_appelds=", ".join(not_supported_appels),
                        actual=repr(priority_list),
                    )),
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

        if isinstance(relate_user_full_name_format_method, str):
            try:
                relate_user_full_name_format_method = (
                    import_string(relate_user_full_name_format_method))
            except ImportError:
                errors = [Warning(
                    msg=(
                            f"{RELATE_USER_FULL_NAME_FORMAT_METHOD}: "
                            f"`{relate_user_full_name_format_method}` "
                            "failed to be imported, "
                            "default format method will be used."
                    ),
                    id="relate_user_full_name_format_method.W001"
                )]
                return errors

        self._custom_full_name_method = relate_user_full_name_format_method
        if not callable(relate_user_full_name_format_method):
            errors.append(Warning(
                msg=(
                        f"{RELATE_USER_FULL_NAME_FORMAT_METHOD}: "
                        f"`{relate_user_full_name_format_method}` is not a callable, "
                        "default format method will be used."
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
                            f"{RELATE_USER_FULL_NAME_FORMAT_METHOD}: "
                            f"`{relate_user_full_name_format_method}` called with '"
                            "args 'first_name', 'last_name' failed with"
                            "exception below:\n"
                            f"{type(e).__name__}: {e!s}\n"
                            f"{format_exc()}\n\n"
                            "Default format method will be used."
                    ),
                    id="relate_user_full_name_format_method.W003"
                ))
            else:
                unexpected_return_value = ""
                if returned_name is None:
                    unexpected_return_value = "None"
                if not isinstance(returned_name, str):
                    unexpected_return_value = type(returned_name).__name__
                elif not returned_name.strip():
                    unexpected_return_value = f"empty string {returned_name}"
                if unexpected_return_value:
                    errors.append(Warning(
                        msg=(f"{RELATE_USER_FULL_NAME_FORMAT_METHOD}: "
                            f"`{relate_user_full_name_format_method}` is expected to "
                             "return a non-empty string, "
                             f"got `{unexpected_return_value}`, "
                             "default format method will be used."),
                        id="relate_user_full_name_format_method.W004"
                    ))
                else:
                    returned_name2 = (
                        relate_user_full_name_format_method("first_name2",
                                                            "last_name2"))
                    if returned_name == returned_name2:
                        errors.append(Warning(
                            msg=(f"{RELATE_USER_FULL_NAME_FORMAT_METHOD}: "
                                f"`{relate_user_full_name_format_method}` "
                                "is expected to "
                                 "return different value with different "
                                 "input, default format method will be used."),
                            id="relate_user_full_name_format_method.W005"
                        ))

        if errors:
            self._custom_full_name_method = None

        return errors


relate_user_method_settings = RelateUserMethodSettingsInitializer()
