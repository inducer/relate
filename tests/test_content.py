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
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%endraw%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%  endraw  %}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHaveValidPage(resp)
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
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%-endraw%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    def test_embedded_raw_block3(self):
        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%- endraw -%}"
        expected_literal = (
            r'<p>\newcommand{\superscript}[1] {\ensuremath{^{\textrm{#1}}}}'
            '\n'
            '<a href="http://example1.com">example1</a></p>\n'
            '<p>value=${#1}<a href="http://example2.com">example2</a></p>')
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

        markdown = TEST_SANDBOX_MARK_DOWN_PATTERN % "{%-endraw-%}"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxHaveValidPage(resp)
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
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextContains(resp, "body", expected_literal)

    # }}}

# vim: fdm=marker
