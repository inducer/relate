from __future__ import division

__copyright__ = "Copyright (C) 2017 Dong Zhuang"

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

import json
from django.test import TestCase
from tests.base_test_mixins import (
    improperly_configured_cache_patch, SingleCoursePageTestMixin)
from tests.test_pages import QUIZ_FLOW_ID
from tests.test_sandbox import SingleCoursePageSandboxTestBaseMixin
from tests.utils import mock


class SingleCoursePageCacheTest(SingleCoursePageTestMixin, TestCase):

    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageCacheTest, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)

    @improperly_configured_cache_patch()
    def test_disable_cache(self, mock_cache):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            from django.core.cache import cache  # noqa

    def test_view_flow_with_cache(self):
        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)
        self.c.get(self.get_page_url_by_ordinal(1))

        with mock.patch("course.content.get_repo_blob") as mock_get_repo_blob:
            resp = self.c.get(self.get_page_url_by_ordinal(0))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_get_repo_blob.call_count, 0)

    def test_view_flow_with_cache_improperly_configured(self):
        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)
        self.c.get(self.get_page_url_by_ordinal(1))

        with improperly_configured_cache_patch():
            resp = self.c.get(self.get_page_url_by_ordinal(0))
            self.assertEqual(resp.status_code, 200)


# {{{ Test Nbconvert for rendering ipynb notebook

QUESTION_MARKUP_FULL = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb") }}
"""

QUESTION_MARKUP_SLICED1 = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb", indices=[0, 1, 2]) }}
"""

QUESTION_MARKUP_SLICED2 = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb", indices=[1, 2]) }}
"""

QUESTION_MARKUP_CLEAR_MARKDOWN = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb", clear_markdown=True) }}
"""

QUESTION_MARKUP_CLEAR_OUTPUT = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb", clear_output=True) }}
"""

QUESTION_MARKUP_CLEAR_ALL = """
type: Page
id: ipynb
content: |

  # Ipython notebook Examples

  {{ render_notebook_cells("test.ipynb", clear_markdown=True, clear_output=True) }}
"""

MARKDOWN_PLACEHOLDER = "wzxhzdk"

TEST_IPYNB_BYTES = json.dumps({
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# First Title of Test NoteBook"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": 1,
            "metadata": {
                "scrolled": True
            },
            "outputs": [
                {
                    "name": "stdout",
                    "output_type": "stream",
                    "text": [
                        "This is function1\n"
                    ]
                }
            ],
            "source": [
                "def function1():\n",
                "    print(\"This is function1\")\n",
                "\n",
                "function1()"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# Second Title of Test NoteBook"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": 2,
            "metadata": {
                "collapsed": True
            },
            "outputs": [],
            "source": [
                "def function2():\n",
                "    print(\"This is function2\")"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": 3,
            "metadata": {},
            "outputs": [
                {
                    "name": "stdout",
                    "output_type": "stream",
                    "text": [
                        "This is function2\n"
                    ]
                }
            ],
            "source": [
                "function2()"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {
                "collapsed": True
            },
            "outputs": [],
            "source": [
                "print(`5**18`)"
            ]
        }
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {
                "name": "ipython",
                "version": 3
            },
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.5.0"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 2
}).encode()

FIRST_TITLE_TEXT = "First Title of Test NoteBook"
SECOND_TITLE_TEXT = "Second Title of Test NoteBook"
TEXT_CELL_HTML_CLASS = "text_cell_render"
CODE_CELL_HTML_CLASS = "code_cell"
CODE_CELL_IN_STR_PATTERN = '<div class="prompt input_prompt">In[%s]:</div>'
CODE_CELL_PRINT_STR1 = "This is function1"
CODE_CELL_PRINT_STR2 = "This is function2"
RELATE_IPYNB_CONVERT_PRE_WRAPPER_TAG_NAME = "relate_ipynb"


def strip_nbsp(s):
    """
    Returns the given HTML with '&nbsp;' (introduced by nbconvert) stripped
    """
    from django.utils.encoding import force_text
    return force_text(s).replace('&nbsp;', '').replace(u'\xa0', '')


def get_nb_html_from_response(response):
    from django.utils.safestring import mark_safe
    return strip_nbsp(mark_safe(response.context["body"]))


class NbconvertRenderTestMixin(SingleCoursePageSandboxTestBaseMixin):
    def assertIsValidNbConversion(self, response):  # noqa
        self.assertNotContains(response, MARKDOWN_PLACEHOLDER)
        self.assertNotContains(response, "```")
        self.assertNotContains(response, "# First Title of Test NoteBook")
        self.assertNotContains(response, "# Second Title of Test NoteBook")
        self.assertNotContains(response, RELATE_IPYNB_CONVERT_PRE_WRAPPER_TAG_NAME)

    def setUp(self):
        super(NbconvertRenderTestMixin, self).setUp()
        patcher = mock.patch("course.content.get_repo_blob_data_cached")
        self.mock_func = patcher.start()
        self.mock_func.return_value = TEST_IPYNB_BYTES
        self.addCleanup(patcher.stop)


class NbconvertRenderTest(NbconvertRenderTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(NbconvertRenderTest, cls).setUpTestData()
        cls.c.force_login(cls.instructor_participation.user)

    def test_full_notebook_render(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_FULL)

        self.assertIsValidNbConversion(resp)
        self.assertContains(resp, TEXT_CELL_HTML_CLASS, count=2)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=4)
        self.assertContains(resp, FIRST_TITLE_TEXT, count=1)
        self.assertContains(resp, SECOND_TITLE_TEXT, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR1, count=2)
        self.assertContains(resp, CODE_CELL_PRINT_STR2, count=2)

        # backtick is properly rendered with highlight
        # for "`5**18`". though this syntax is not allowed in PY3
        self.assertContains(
            resp,
            '<span class="err">`</span><span class="mi">5</span>')

        nb_html = get_nb_html_from_response(resp)
        for i in range(1, 4):
            self.assertInHTML(CODE_CELL_IN_STR_PATTERN % i, nb_html)

    def test_notebook_sliced1(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_SLICED1)
        self.assertIsValidNbConversion(resp)
        self.assertContains(resp, TEXT_CELL_HTML_CLASS, count=2)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=1)
        self.assertContains(resp, FIRST_TITLE_TEXT, count=1)
        self.assertContains(resp, SECOND_TITLE_TEXT, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR1, count=2)
        self.assertNotContains(resp, CODE_CELL_PRINT_STR2)

        nb_html = get_nb_html_from_response(resp)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 1, nb_html, count=1)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 2, nb_html, count=0)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 3, nb_html, count=0)

    def test_notebook_sliced2(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_SLICED2)
        self.assertIsValidNbConversion(resp)
        self.assertContains(resp, TEXT_CELL_HTML_CLASS, count=1)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=1)
        self.assertNotContains(resp, FIRST_TITLE_TEXT)
        self.assertContains(resp, SECOND_TITLE_TEXT, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR1, count=2)
        self.assertNotContains(resp, CODE_CELL_PRINT_STR2)

        # code highlight functions (in terms of rendered ipynb notebook cells only)
        import six
        if six.PY3:
            self.assertRegex(resp.context["body"], 'class="\w*\s*highlight[^\w]')
        self.assertContains(resp, " highlight hl-ipython3")
        self.assertContains(resp,
                            '<span class="nb">print</span>'
                            '<span class="p">(</span>',
                            count=1)

        nb_html = get_nb_html_from_response(resp)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 1, nb_html, count=1)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 2, nb_html, count=0)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % 3, nb_html, count=0)

    def test_notebook_clear_markdown(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_CLEAR_MARKDOWN)
        self.assertIsValidNbConversion(resp)
        self.assertNotContains(resp, TEXT_CELL_HTML_CLASS)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=4)
        self.assertNotContains(resp, FIRST_TITLE_TEXT)
        self.assertNotContains(resp, SECOND_TITLE_TEXT)

        nb_html = get_nb_html_from_response(resp)
        for i in range(1, 4):
            self.assertInHTML(CODE_CELL_IN_STR_PATTERN % i, nb_html, count=1)

    def test_notebook_clear_output(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_CLEAR_OUTPUT)
        self.assertIsValidNbConversion(resp)
        self.assertContains(resp, TEXT_CELL_HTML_CLASS, count=2)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=4)
        self.assertContains(resp, FIRST_TITLE_TEXT, count=1)
        self.assertContains(resp, SECOND_TITLE_TEXT, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR1, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR2, count=1)

        nb_html = get_nb_html_from_response(resp)
        for i in range(1, 4):
            self.assertInHTML(CODE_CELL_IN_STR_PATTERN % i, nb_html, count=0)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % "", nb_html, count=4)

    def test_notebook_clear_markdown_and_output(self):
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP_CLEAR_ALL)
        self.assertIsValidNbConversion(resp)
        self.assertNotContains(resp, TEXT_CELL_HTML_CLASS)
        self.assertContains(resp, CODE_CELL_HTML_CLASS, count=4)
        self.assertNotContains(resp, FIRST_TITLE_TEXT)
        self.assertNotContains(resp, SECOND_TITLE_TEXT)
        self.assertContains(resp, CODE_CELL_PRINT_STR1, count=1)
        self.assertContains(resp, CODE_CELL_PRINT_STR2, count=1)

        nb_html = get_nb_html_from_response(resp)
        for i in range(1, 4):
            self.assertInHTML(CODE_CELL_IN_STR_PATTERN % i, nb_html, count=0)
        self.assertInHTML(CODE_CELL_IN_STR_PATTERN % "", nb_html, count=4)


# }}}


TEST_SANDBOX_MARK_DOWN_PATTERN = r"""
type: Page
id: test_endraw
content: |
    # Title
    {%% raw %%}\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}{%% endraw %%}
    [example1](http://example1.com)
    {%% raw %%}
    value=${#1}
    %s
    [example2](http://example2.com)
"""  # noqa


class YamlJinjaExpansionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    # {{{ test https://github.com/inducer/relate/pull/376 which
    # fixed https://github.com/inducer/relate/issues/373

    def test_embedded_raw_block1(self):
        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{% endraw %}"
        expected_literal = (
            r'<p>\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}'
            '\n'
            '<a href="http://example1.com">example1</a></p>\n'
            '<p>value=${#1}</p>\n'
            '<p><a href="http://example2.com">example2</a></p>')
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%endraw%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%  endraw  %}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    def test_embedded_raw_block2(self):
        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%- endraw %}"

        expected_literal = (
            r'<p>\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}'
            '\n'
            '<a href="http://example1.com">example1</a></p>\n'
            '<p>value=${#1}\n'
            '<a href="http://example2.com">example2</a></p>')
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%-endraw%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    def test_embedded_raw_block3(self):
        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%- endraw -%}"
        expected_literal = (
            r'<p>\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}'
            '\n'
            '<a href="http://example1.com">example1</a></p>\n'
            '<p>value=${#1}<a href="http://example2.com">example2</a></p>')
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%-endraw-%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    def test_embedded_raw_block4(self):
        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{% endraw -%}"
        expected_literal = (
            r'<p>\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}'
            '\n'
            '<a href="http://example1.com">example1</a></p>\n'
            '<p>value=${#1}\n'
            '<a href="http://example2.com">example2</a></p>')
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    # }}}

# vim: fdm=marker
