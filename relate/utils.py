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
import django.forms as forms


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(StyledForm, self).__init__(*args, **kwargs)


class StyledInlineForm(forms.Form):
    def __init__(self, *args, **kwargs):
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-inline"
        self.helper.label_class = "sr-only"

        super(StyledInlineForm, self).__init__(*args, **kwargs)


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(StyledModelForm, self).__init__(*args, **kwargs)


def settings_context_processor(request):
    from django.conf import settings
    return {
        "student_sign_in_view": settings.STUDENT_SIGN_IN_VIEW,
        "maintenance_mode": settings.RELATE_MAINTENANCE_MODE,
        "site_announcement": getattr(settings, "RELATE_SITE_ANNOUNCEMENT", None),
        }


def as_local_time(datetime):
    """Takes an timezone-aware datetime and applies the server timezone."""
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return datetime.astimezone(tz)


def localize_datetime(datetime):
    """Takes an timezone-naive datetime and applies the server timezone."""
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return tz.localize(datetime)


def local_now():
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    from datetime import datetime
    return tz.localize(datetime.now())


def format_datetime_local(datetime, format='medium'):
    """Format the output of a datetime object to a localized string"""
    from babel.dates import format_datetime
    from django.conf import settings
    from django.utils.translation.trans_real import to_locale
    # See http://babel.pocoo.org/docs/api/dates/#date-and-time-formatting
    # for customizing the output format.
    try:
        result = format_datetime(
                datetime, format, locale=to_locale(settings.LANGUAGE_CODE))
    except ValueError:
        result = format_datetime(datetime, format, locale="en_US")

    return result


# {{{ dict_to_struct

class Struct(object):
    def __init__(self, entries):
        for name, val in six.iteritems(entries):
            self.__dict__[name] = val

    def __repr__(self):
        return repr(self.__dict__)


def dict_to_struct(data):
    if isinstance(data, list):
        return [dict_to_struct(d) for d in data]
    elif isinstance(data, dict):
        return Struct({k: dict_to_struct(v) for k, v in six.iteritems(data)})
    else:
        return data


def struct_to_dict(data):
    return dict(
            (name, val)
            for name, val in data.__dict__.iteritems()
            if not name.startswith("_"))

# }}}

# vim: foldmethod=marker
