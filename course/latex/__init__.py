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

import six
import re

from django.utils.translation import ugettext as _

from course.latex.converter import get_tex2img_class
from course.latex.latex import TexDoc
from course.latex.utils import (
    replace_latex_space_seperator, strip_spaces)

TIKZ_PGF_RE = re.compile(r"\\begin\{(?:tikzpicture|pgfpicture)\}")
DEFAULT_IMG_HTML_CLASS = "img-responsive"


def tex_to_img_tag(tex_source, *args, **kwargs):
    '''Convert LaTex to IMG tag'''

    compiler = kwargs.get("compiler", None)
    if not compiler:
        raise ValueError(_("'compiler' must be specified."))

    image_format = kwargs.get("image_format", "")
    if not image_format:
        raise ValueError(_("'image_format' must be specified."))

    output_dir = kwargs.get("output_dir")

    tex_filename = kwargs.get("tex_filename", None)
    tex_preamble = kwargs.get("tex_preamble", "")
    tex_preamble_extra = kwargs.get("tex_preamble_extra", "")

    force_regenerate = kwargs.get("force_regenerate", False)
    html_class_extra = kwargs.get("html_class_extra", "")
    empty_pagestyle = kwargs.get("empty_pagestyle", True)
    alt = kwargs.get("alt", None)

    # remove spaces added to latex code in jinja template.
    tex_source = replace_latex_space_seperator(
        strip_spaces(tex_source, allow_single_empty_line=True))
    tex_preamble = replace_latex_space_seperator(
        strip_spaces(tex_preamble, allow_single_empty_line=True))
    tex_preamble_extra = replace_latex_space_seperator(
        strip_spaces(tex_preamble_extra,
                     allow_single_empty_line=True))

    if html_class_extra:
        if isinstance(html_class_extra, list):
            html_class_extra = " ".join (html_class_extra)
        elif not isinstance(html_class_extra, six.string_types):
            raise ValueError(
                _('"html_class_extra" must be a string or a list'))
        html_class = "%s %s" %(DEFAULT_IMG_HTML_CLASS, html_class_extra)
    else: html_class = DEFAULT_IMG_HTML_CLASS

    texdoc = TexDoc(
        tex_source, preamble=tex_preamble,
        preamble_extra=tex_preamble_extra, empty_pagestyle=empty_pagestyle)

    # empty document
    if not texdoc.document.strip():
        return ""

    if (compiler == "latex"
        and image_format == "png"
        and re.search(TIKZ_PGF_RE, tex_source)):
        image_format = "svg"

    tex2img_class = get_tex2img_class(compiler, image_format)

    if not alt:
        alt = texdoc.document

    if alt:
        from django.utils.html import escape
        alt = "alt='%s'" % alt.strip().replace("\n","")

    latex2img = tex2img_class(
        tex_source=texdoc.as_latex(),
        tex_filename=tex_filename,
        output_dir=output_dir
        )

    return (
        "<img src='%(src)s' "
        "class='%(html_class)s' %(alt)s>"
        % {
            "src": latex2img.get_data_uri_cached(force_regenerate),
            "html_class": html_class,
            "alt": alt,
        })

# vim: foldmethod=marker
