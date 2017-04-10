# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

"""
LANG_INFO is a dictionary structure to provide meta information about languages.

About name_local: capitalize it as if your language name was appearing
inside a sentence in your language.
The 'fallback' key can be used to specify a special fallback logic which doesn't
follow the traditional 'fr-ca' -> 'fr' fallback logic.
"""

LANG_INFO = {
    'zh-cn': {
        'fallback': ['zh-hans'],
        'bidi': False,
        'code': 'zh-cn',
        'name': 'Simplified Chinese',
        'name_local': '简体中文',
    },
    'zh-tw': {
        'fallback': ['zh-hant'],
        'bidi': False,
        'code': 'zh-tw',
        'name': 'Tranditional Chinese',
        'name_local': '繁体中文',
    },
    'zh-hk': {
        'fallback': ['zh-hant'],
        'bidi': False,
        'code': 'zh-tw',
        'name': 'Tranditional Chinese',
        'name_local': '繁体中文',
    },
}
