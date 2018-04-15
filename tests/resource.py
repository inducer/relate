from __future__ import division

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

from django.core.mail.backends.locmem import EmailBackend as LocMemEmailBackend


def my_customized_get_full_name_method(first_name, last_name):
    return "%s %s" % (first_name.title(), last_name.title())


def my_customized_get_full_name_method_invalid(first_name, last_name):
    return None


my_customized_get_full_name_method_invalid_str = "some_string"


def my_custom_get_masked_profile_method_valid(u):
    return "%s%s" % ("User", str(u.pk + 100))


my_custom_get_masked_profile_method_invalid_str = "some_string"


def my_custom_get_masked_profile_method_valid_but_return_none(u):
    return


def my_custom_get_masked_profile_method_valid_but_return_emtpy_string(u):
    return "  "


class MyFakeEmailBackend(LocMemEmailBackend):
    pass
