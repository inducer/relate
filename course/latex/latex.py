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

import re

from django.utils.translation import ugettext as _

from .utils import strip_comments, strip_spaces

class TexDocParseError(Exception):
    pass

class TexDocMissingElementError(TexDocParseError):
    pass

class TexDocWrongElementOrderError(TexDocParseError):
    pass

class TexDoc():
    """
    Defines a LaTeX document
    """
    preamble = ""
    document = ""
    has_preamble = False
    has_begindoc = False
    has_enddoc = False

    def is_empty_pagestyle_already(self):
        match = re.search(r"\\pagestyle{\s?empty\s?}", self.preamble)
        if match:
            return True
        return False

    def parse(self, latex, test=False):
        """
        parse the doc into preamble and document. If test=True, the
        method will try to find out which elements of the latex code
        is missing.
        """
        ele_re_tuple = (
            (r"\documentclass",
             r"\\documentclass(\[[\w,= ]*\])?{\w*}"),
            (r"\begin{document}", r"\\begin\{document\}"),
            (r"\end{document}", r"\\end\{document\}")
        )
        ele_position_list = []
        required_ele_list = []
        has_ele = []

        for ele, pattern in ele_re_tuple:
            required_ele_list.append(ele)
            iter = re.finditer(pattern, latex)

            matched_indice = [m.start(0) for m in iter]
            matched_len = len(matched_indice)
            if matched_len == 0:
                if not test:
                    raise TexDocMissingElementError(
                        _("No %s found in latex source") % ele)
                else:
                    has_ele.append(False)
            elif matched_len > 1:
                raise TexDocParseError(
                    _("More than one %s found in latex source") % ele)
            else:
                if test:
                    has_ele.append(True)
                ele_position_list.append(matched_indice[0])

        if test:
            [self.has_preamble, self.has_begindoc, self.has_enddoc] = has_ele

        if not ele_position_list == sorted(ele_position_list):
            raise TexDocWrongElementOrderError(
                _("The occurance of %s are not in proper order")
                % ",".join(required_ele_list))

        if not test:
            [preamble, document] = latex.split((r"\begin{document}"))
            document = document.split((r"\end{document}"))[0]
            self.preamble = strip_spaces(preamble)
            self.document = strip_spaces(document, allow_single_empty_line=True)
            assert self.preamble is not None
            assert self.document is not None

    def as_latex(self):
        """
        Assemble LaTeX Document
        """
        latex = ""
        if self.empty_pagestyle:
            if not self.is_empty_pagestyle_already():
                self.preamble += "\n\\pagestyle{empty}\n"

        latex += self.preamble
        latex += "\\begin{document}\n"
        latex += self.document
        latex += "\\end{document}\n"

        return latex

    def __str__(self):
        return self.document

    def __unicode__(self):
        return self.document

    def __init__(self, text=None, preamble="", preamble_extra="",
                 empty_pagestyle=False):
        """
        Parse LaTeX document
        :param text: string. Full latex document, or body only if
        preamble or preamble_extra are given.
        :param preamble: string. If full document is provided in
        text, this value will be neglected.
        :param preamble_extra: string. Append to existing preamle.
        :param empty_pagestyle: bool. If True, the pagestyle will
        be set as "empty". We are not using
        \documentclass{standalone}.
        """
        if not text:
            raise ValueError(_("No LaTeX source code is provided."))

        text = strip_comments(text)
        try:
            self.parse(text)
        except TexDocMissingElementError:
            self.parse(text, test=True)
            if self.has_preamble:
                # begin_document or end_document is missing
                raise
            elif not preamble and not preamble_extra:
                raise

            # in this case, preamble code and document body code
            # are seperated, try to assemble them up.
            else:
                if not self.has_begindoc:
                    text = "%s\n%s" % ("\\begin{document}", text)
                if not self.has_enddoc:
                    text = "%s\n%s" % (text, "\\end{document}")

                text = "%s\n%s\n%s" % (
                    strip_comments(preamble),
                    strip_comments(preamble_extra),
                    text)
                self.parse(text)

        except:
            raise

        self.empty_pagestyle = empty_pagestyle