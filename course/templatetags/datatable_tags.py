# -*- coding: utf-8 -*-

from __future__ import division

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
from django import template
from django.templatetags.i18n import TemplateSyntaxError, GetLanguageInfoNode
from django.utils import six, translation

register = template.Library()

# Map DataTables's i18n files with django supported languang_code format
DATA_TABLES_I18N_MAP_DICT={
    "af": "Afrikaans",
    "sq": "Albanian",
    "ar": "Arabic",
    "hy": "Armenian",
    "az": "Azerbaijan",
    "bn": "Bangla",
    "eu": "Basque",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "zh-tw": "Chinese-traditional",
    "zh-hk": "Chinese-traditional",
    "zh-cn": "Chinese",
    "zh-hans": "Chinese",
    "zh-hant": "Chinese-traditional",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "gl": "Galician",
    "ka": "Georgian",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "is": "Icelandic",
    "id": "Indonesian",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ky": "Kyrgyz",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "mk": "Macedonian",
    "ms": "Malay",
    "mn": "Mongolian",
    "ne": "Nepali",
    "nb": "Norwegian",
    "pl": "Polish",
    "pt-br": "Portuguese-Brasil",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sr-latn": "Serbian",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "es": "Spanish",
    "sw": "Swahili",
    "sv": "Swedish",
    "ta": "Tamil",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukranian", # typo in original resource
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese"
}

class GetDataTableLang(GetLanguageInfoNode):
    def render(self, context):
        lang_code = self.lang_code.resolve(context)
        lang_info = translation.get_language_info(lang_code)
        datatable_lang = DATA_TABLES_I18N_MAP_DICT.get(lang_info["code"], "English")
        context[self.variable] = datatable_lang
        return ''

@register.tag("get_datatable_language")
def do_get_datatable_language(parser, token):
    args = token.split_contents()
    if len(args) != 3 or args[1] != 'as':
        raise TemplateSyntaxError("'%s' requires 'as variable' (got %r)" % (args[0], args[1:]))
    return GetDataTableLang(parser.compile_filter("LANGUAGE_CODE"), args[2])