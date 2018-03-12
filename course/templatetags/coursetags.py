# -*- coding: utf-8 -*-

__copyright__ = "Copyright (C) 2016 Dong Zhuang, Andreas Kloeckner"

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

from django.template import Library, Node, TemplateSyntaxError
from django.utils import translation
from relate.utils import to_datatables_lang_name

register = Library()

# {{{ get language_code in JS traditional naming format


class GetCurrentLanguageJsFmtNode(Node):
    def __init__(self, variable):
        self.variable = variable

    def render(self, context):
        datatables_lang_name = to_datatables_lang_name(translation.get_language())
        context[self.variable] = datatables_lang_name
        return ''


@register.tag("get_current_js_lang_name")
def do_get_current_js_lang_name(parser, token):
    """
    This will store the current language in the context, in js lang format.
    This is different with built-in do_get_current_language, which returns
    languange name like "en-us", "zh-cn", with the country code using lower
    case. This method return lang name "en-US", "zh-CN", as most js packages
    with i18n are providing translations using that naming format.

    Usage::

        {% get_current_language_js_lang_format as language %}

    This will fetch the currently active language name with js tradition and
    put it's value into the ``language`` context variable.
    """
    # token.split_contents() isn't useful here because this tag doesn't
    # accept variable as arguments
    args = token.contents.split()
    if len(args) != 3 or args[1] != 'as':
        raise TemplateSyntaxError("'get_current_js_lang_name' requires "
                "'as variable' (got %r)" % args)
    return GetCurrentLanguageJsFmtNode(args[2])

# }}}


# {{{ filter for participation.has_permission()

@register.filter(name='has_permission')
def has_permission(participation, arg):
    """
    Check if a participation instance has specific permission.
    :param a :class:`participation:` instance
    :param arg: String, with permission and arguments separated by comma
    :return: a :class:`bool`
    """
    has_pperm = False
    try:
        arg_list = [s.strip() for s in arg.split(",")]
        perm = arg_list[0]
        argument = None
        if len(arg_list) > 1:
            argument = arg_list[1]
        has_pperm = participation.has_permission(perm, argument)
    except Exception:
        # fail silently
        pass

    return has_pperm

# }}}
