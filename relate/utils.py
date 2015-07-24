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


import django.forms as forms


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(StyledForm, self).__init__(*args, **kwargs)


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
        }


def as_local_time(datetime, formatted=False):
    """Takes an timezone-aware datetime and applies the server timezone."""
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    if formatted:
        from babel.dates import format_datetime
        return format_datetime(datetime.astimezone(tz), locale=settings.LANGUAGE_CODE)
    else:
        return datetime.astimezone(tz)


def localize_datetime(datetime):
    """Takes an timezone-naive datetime and applies the server timezone."""
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    return tz.localize(datetime)


def local_now(formatted=False):
    from django.conf import settings
    from pytz import timezone
    tz = timezone(settings.TIME_ZONE)
    from datetime import datetime
    if formatted:
        from babel.dates import format_datetime
        return format_datetime(tz.localize(datetime.now()), locale=settings.LANGUAGE_CODE)
    else:
        return tz.localize(datetime.now())


# {{{ dict_to_struct

class Struct(object):
    def __init__(self, entries):
        for name, val in entries.iteritems():
            self.__dict__[name] = dict_to_struct(val)

    def __repr__(self):
        return repr(self.__dict__)


def dict_to_struct(data):
    if isinstance(data, list):
        return [dict_to_struct(d) for d in data]
    elif isinstance(data, dict):
        return Struct(data)
    else:
        return data


def struct_to_dict(data):
    return dict(
            (name, val)
            for name, val in data.__dict__.iteritems()
            if not name.startswith("_"))

# }}}

# vim: foldmethod=marker
