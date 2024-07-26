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


register = Library()


# {{{ get language_code in JS traditional naming format

class GetCurrentLanguageJsFmtNode(Node):
    def __init__(self, variable):
        self.variable = variable

    def render(self, context):
        lang_name = (
            translation.to_locale(translation.get_language()).replace("_", "-"))
        context[self.variable] = lang_name
        return ""


@register.tag("get_current_js_lang_name")
def do_get_current_js_lang_name(parser, token):
    """
    This will store the current language in the context, in js lang format.
    This is different with built-in do_get_current_language, which returns
    language name like "en-us", "zh-hans". This method return lang name
    "en-US", "zh-Hans",  with the country code capitallized if country code
    has 2 characters, and capitalize first if country code has more than 2
    characters.

    Usage::

        {% get_current_language_js_lang_format as language %}

    This will fetch the currently active language name with js tradition and
    put it's value into the ``language`` context variable.
    """
    # token.split_contents() isn't useful here because this tag doesn't
    # accept variable as arguments
    args = token.contents.split()
    if len(args) != 3 or args[1] != "as":
        raise TemplateSyntaxError("'get_current_js_lang_name' requires "
                "'as variable' (got %r)" % args)
    return GetCurrentLanguageJsFmtNode(args[2])

# }}}


# {{{ filter for participation.has_permission()

@register.filter(name="has_permission")
def has_permission(participation, arg):
    """
    Check if a participation instance has specific permission.
    :param participation: a :class:`participation:` instance
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


@register.filter(name="may_set_fake_time")
def may_set_fake_time(user):
    """
    Check if a user may set fake time.
    :param user: a :class:`accounts.User:` instance
    :return: a :class:`bool`
    """
    from course.views import may_set_fake_time as msf
    return msf(user)


@register.filter(name="may_set_pretend_facility")
def may_set_pretend_facility(user):
    """
    Check if a user may set pretend_facility
    :param user: a :class:`accounts.User:` instance
    :return: a :class:`bool`
    """
    from course.views import may_set_pretend_facility as mspf
    return mspf(user)


@register.filter(name="commit_message_as_html")
def commit_message_as_html(commit_sha, repo):
    from course.versioning import _get_commit_message_as_html
    return _get_commit_message_as_html(repo, commit_sha)


@register.filter(name="get_item")
def get_item(dictionary, key):
    return dictionary.get(key, None)


@register.filter(name="get_item_or_key")
def get_item_or_key(dictionary, key):
    return dictionary.get(key, key)


@register.filter(name="startswith")
def startswith(s, arg):
    return s.startswith(arg)
