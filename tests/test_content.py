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

import pytz
import os
import json
import unittest
import pytest
import datetime
import stat
from dulwich.repo import Tree

from django.test import TestCase, RequestFactory, override_settings
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from course.models import FlowSession
from course import content
from course import page

from tests.base_test_mixins import (
    SingleCourseTestMixin,
    improperly_configured_cache_patch, SingleCoursePageTestMixin,
    SingleCourseQuizPageTestMixin, MockAddMessageMixing, HackRepoMixin)
from tests.test_sandbox import SingleCoursePageSandboxTestBaseMixin
from tests.utils import mock
from tests import factories


class SingleCoursePageCacheTest(SingleCoursePageTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
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
                '    print("This is function1")\n',
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
                '    print("This is function2")'
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
    from django.utils.encoding import force_str
    return force_str(s).replace('&nbsp;', '').replace('\xa0', '')


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
        super().setUp()
        patcher = mock.patch("course.content.get_repo_blob_data_cached")
        self.mock_func = patcher.start()
        self.mock_func.return_value = TEST_IPYNB_BYTES
        self.addCleanup(patcher.stop)


class NbconvertRenderTest(NbconvertRenderTestMixin, TestCase):

    force_login_student_for_each_test = False

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.c.force_login(cls.instructor_participation.user)

    def test_notebook_page_view(self):
        self.start_flow(flow_id="001-linalg-recap",
                        course_identifier=self.course.identifier,
                        assume_success=False)
        fs = FlowSession.objects.last()
        resp = self.c.get(
            self.get_page_url_by_page_id(
                "ipynb", course_identifier=self.course.identifier,
                flow_session_id=fs.id))
        self.assertEqual(resp.status_code, 200)

    def test_notebook_file_not_found(self):
        self.start_flow(flow_id="001-linalg-recap",
                        course_identifier=self.course.identifier,
                        assume_success=False)
        with mock.patch(
                "course.content.get_repo_blob_data_cached") as mock_get_blob_cached:

            from django.core.exceptions import ObjectDoesNotExist
            mock_get_blob_cached.side_effect = ObjectDoesNotExist()

            fs = FlowSession.objects.last()
            with self.assertRaises(ObjectDoesNotExist):
                self.c.get(
                    self.get_page_url_by_page_id(
                        "ipynb", course_identifier=self.course.identifier,
                        flow_session_id=fs.id))

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
        self.assertRegex(resp.context["body"], r'class="\w*\s*highlight[^\w]')
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


class GetCourseCommitShaTest(SingleCourseTestMixin, TestCase):
    # test content.get_course_commit_sha
    def setUp(self):
        super().setUp()
        self.valid_sha = self.course.active_git_commit_sha
        self.new_sha = "some_sha"
        self.course.active_git_commit_sha = self.new_sha
        self.course.save()

    def test_no_participation(self):
        self.assertEqual(
            content.get_course_commit_sha(
                course=self.course, participation=None).decode(), self.new_sha)

    def test_invalid_preview_sha(self):
        invalid_sha = "invalid_sha"
        self.ta_participation.preview_git_commit_sha = invalid_sha
        self.ta_participation.save()

        self.assertEqual(
            content.get_course_commit_sha(
                course=self.course, participation=self.ta_participation).decode(),
            self.new_sha)

    def test_invalid_preview_sha_error_raised(self):
        invalid_sha = "invalid_sha"
        self.ta_participation.preview_git_commit_sha = invalid_sha
        self.ta_participation.save()

        with self.assertRaises(content.CourseCommitSHADoesNotExist) as cm:
            content.get_course_commit_sha(
                course=self.course, participation=self.ta_participation,
                raise_on_nonexistent_preview_commit=True)

        expected_error_msg = ("Preview revision '%s' does not exist--"
                      "showing active course content instead."
                      % invalid_sha)
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_passed_repo_not_none(self):
        with self.get_course_page_context(self.ta_participation.user) as pctx:
            self.assertEqual(
                content.get_course_commit_sha(
                    self.course, self.ta_participation,
                    repo=pctx.repo).decode(), self.course.active_git_commit_sha)

    def test_preview_passed_repo_not_none(self):
        self.ta_participation.preview_git_commit_sha = self.valid_sha
        self.ta_participation.save()

        with self.get_course_page_context(self.ta_participation.user) as pctx:
            self.assertEqual(
                content.get_course_commit_sha(
                    self.course, self.ta_participation,
                    repo=pctx.repo).decode(), self.valid_sha)

    def test_repo_is_subdir_repo(self):
        self.course.course_root_path = "/my_subdir"
        self.course.save()
        self.ta_participation.preview_git_commit_sha = self.valid_sha
        self.ta_participation.save()

        with self.get_course_page_context(self.ta_participation.user) as pctx:
            self.assertEqual(
                content.get_course_commit_sha(
                    self.course, self.ta_participation,
                    repo=pctx.repo).decode(), self.valid_sha)


@pytest.mark.slow
class SubDirRepoTest(SingleCourseQuizPageTestMixin, MockAddMessageMixing, TestCase):
    # test subdir repo (for cases not covered by other tests)

    subdir_branch_commit_sha = "fb3fffe4e88e52a91446a1ecdba502e8ee6a6031"

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.course.course_root_path = "course_content"
        cls.course.active_git_commit_sha = cls.subdir_branch_commit_sha
        cls.course.save()

    def test_flowpage(self):
        self.start_flow(self.flow_id)
        page_id = "half"
        submit_answer_response, _ = (
            self.default_submit_page_answer_by_page_id_and_test(page_id)
        )
        self.assertEqual(submit_answer_response.status_code, 200)

    def test_validation(self):
        self.post_update_course_content(self.subdir_branch_commit_sha)
        self.assertAddMessageCallCount(2)
        self.assertAddMessageCalledWith(
            ["Course content validated OK", "Update applied."])


class GetRepoBlobTest(SingleCourseTestMixin, TestCase):
    # test content.get_repo_blob (for cases not covered by other tests)
    def setUp(self):
        super().setUp()
        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = self.instructor_participation.user

        from course.utils import CoursePageContext
        self.pctx = CoursePageContext(request, self.course.identifier)

    def test_repo_root_not_allow_tree_key_error(self):
        with self.pctx.repo as repo:
            with self.assertRaises(ObjectDoesNotExist) as cm:
                content.get_repo_blob(
                    repo, "", self.course.active_git_commit_sha.encode(),
                    allow_tree=False)
            expected_error_msg = "resource '(repo root)' is a directory, not a file"
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_access_directory_content_type_error(self):
        path_parts = "course.yml", "cc.png"
        full_name = os.path.join(*path_parts)
        with self.pctx.repo as repo:
            with self.assertRaises(ObjectDoesNotExist) as cm:
                content.get_repo_blob(
                    repo, full_name, self.course.active_git_commit_sha.encode(),
                    allow_tree=True)
            expected_error_msg = (
                    "'%s' is not a directory, cannot lookup nested names"
                    % path_parts[0])
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_resource_is_a_directory_error(self):
        full_name = "images"
        with self.pctx.repo as repo:
            with self.assertRaises(ObjectDoesNotExist) as cm:
                content.get_repo_blob(
                    repo, full_name, self.course.active_git_commit_sha.encode(),
                    allow_tree=False)
            expected_error_msg = (
                    "resource '%s' is a directory, not a file" % full_name)
            self.assertIn(expected_error_msg, str(cm.exception))


class GitTemplateLoaderTest(SingleCourseTestMixin, TestCase):
    # test content.GitTemplateLoader
    def setUp(self):
        super().setUp()
        rf = RequestFactory()
        request = rf.get(self.course_page_url)
        request.user = self.instructor_participation.user
        from course.utils import CoursePageContext
        self.pctx = CoursePageContext(request, self.course.identifier)

    def test_object_not_found(self):
        environment = mock.MagicMock()
        template = mock.MagicMock()
        with self.pctx.repo as repo:
            loader = content.GitTemplateLoader(
                repo, self.course.active_git_commit_sha.encode())
            with mock.patch(
                    "course.content.get_repo_blob_data_cached",
                    side_effect=ObjectDoesNotExist):
                with self.assertRaises(content.TemplateNotFound):
                    loader.get_source(environment=environment,
                                      template=template)

    def test_get_source_uptodate(self):
        environment = mock.MagicMock()
        template = mock.MagicMock()
        with self.pctx.repo as repo:
            with mock.patch(
                    "course.content.get_repo_blob_data_cached",
                    return_value=b"blahblah"):
                loader = content.GitTemplateLoader(
                    repo, self.course.active_git_commit_sha.encode())
                _, __, uptodate = loader.get_source(environment=environment,
                                                    template=template)
                self.assertFalse(uptodate())


class YamlBlockEscapingFileSystemLoaderTest(SingleCourseTestMixin, TestCase):
    # test content.YamlBlockEscapingFileSystemLoader
    pass


class GetYamlFromRepoTest(SingleCourseTestMixin, TestCase):
    # test content.get_yaml_from_repo
    def setUp(self):
        super().setUp()
        rf = RequestFactory()
        request = rf.get(self.course_page_url)
        request.user = self.instructor_participation.user
        from course.utils import CoursePageContext
        self.pctx = CoursePageContext(request, self.course.identifier)

    def test_file_uses_tab_in_indentation(self):
        fake_yaml_bytestream = b"\tabcd\n"

        class _Blob:
            def __init__(self):
                self.data = fake_yaml_bytestream

        with mock.patch("course.content.get_repo_blob") as mock_get_repo_blob:
            mock_get_repo_blob.return_value = _Blob()
            with self.assertRaises(ValueError) as cm:
                with self.pctx.repo as repo:
                    content.get_yaml_from_repo(
                        repo, "course.yml",
                        self.course.active_git_commit_sha.encode())

            expected_error_msg = (
                "File uses tabs in indentation. "
                "This is not allowed.")

            self.assertIn(expected_error_msg, str(cm.exception))


class AttrToStringTest(unittest.TestCase):
    # test content._attr_to_string
    def test(self):
        self.assertEqual(content._attr_to_string("disabled", None), "disabled")
        self.assertEqual(content._attr_to_string(
            "id", '"abc"'), "id='\"abc\"'")
        self.assertEqual(content._attr_to_string("id", "abc"), 'id="abc"')


MARKDOWN_WITH_LINK_FRAGMENT = """
type: Page
id: frag
content: |

    # Test frag in path

    [A static page](staticpage:test#abcd)
    <a href="blablabla">
    <a href=http://foo.com />
    <table bootstrop></table>
    <!-- This is an invalid link -->
    [A static page](course:test#abcd)

    ## link to another course
    [A static page](course:another-course)

    ## calendar linkes
    [A static page](calendar:)

    ## images
    ![alt text](https://raw.githubusercontent.com/inducer/relate/master/doc/images/screenshot.png "Example")
    <img src="repo:images/cc.png">

    ## object data
    <object width="400" height="400" data="helloworld.swf">
    <object data="repo:images/cc.png">
"""  # noqa


class TagProcessingHTMLParserAndLinkFixerTreeprocessorTest(
        SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_embedded_raw_block1(self):
        another_course = factories.CourseFactory(identifier="another-course")
        markdown = MARKDOWN_WITH_LINK_FRAGMENT
        expected_literal = [
            '/course/test-course/page/test/#abcd',
            '<a href="blablabla">',

            # handle_startendtag
            '<a href="http://foo.com"/>',

            # handle_comment
            '<!-- This is an invalid link -->',

            # invalid link
            "data:text/plain;base64,SW52YWxpZCBjaGFyYWN0ZXIgaW4gUkVMQVR"
            "FIFVSTDogY291cnNlOnRlc3QjYWJjZA==",

            # images
            "https://raw.githubusercontent.com/inducer/relate/master/"
            "doc/images/screenshot.png",
            "/course/test-course/file-version/%s/images/cc.png"
            % self.course.active_git_commit_sha,

            # object data
            'data="helloworld.swf"',
            "/course/test-course/file-version/%s/images/cc.png"
            % self.course.active_git_commit_sha,
        ]

        resp = self.get_page_sandbox_preview_response(markdown)

        self.assertSandboxHasValidPage(resp)

        for literal in (expected_literal
                        + [self.get_course_page_url(),
                           self.get_course_page_url(another_course.identifier)]):
            with self.subTest(literal=literal):
                self.assertResponseContextContains(resp, "body", literal)

        table_literals = [
            '<table bootstrop class="table table-condensed"></table>',
            '<table class="table table-condensed" bootstrop></table>',
        ]
        if table_literals[0] not in resp.context["body"]:
            self.assertResponseContextContains(resp, "body", table_literals[1])

    def test_course_is_none(self):
        md = mock.MagicMock()
        commit_sha = mock.MagicMock()
        reverse_func = mock.MagicMock()
        processor = content.LinkFixerTreeprocessor(md, None,
                                                   commit_sha, reverse_func)
        result = processor.get_course_identifier()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)


class YamlBlockEscapingGitTemplateLoaderTest(SingleCourseTestMixin, TestCase):
    # test content.YamlBlockEscapingGitTemplateLoader
    # (for cases not covered by other tests)

    def setUp(self):
        super().setUp()
        rf = RequestFactory()
        request = rf.get(self.course_page_url)
        request.user = self.instructor_participation.user
        from course.utils import CoursePageContext
        self.pctx = CoursePageContext(request, self.course.identifier)

    def test_load_not_yaml(self):
        environment = mock.MagicMock()
        with mock.patch(
                "course.content.process_yaml_for_expansion") as mock_process_yaml:
            with self.pctx.repo as repo:
                loader = content.YamlBlockEscapingGitTemplateLoader(
                    repo, self.course.active_git_commit_sha.encode())
                result = loader.get_source(environment, "content-macros.jinja")
                source, _, _ = result
                self.assertIsNotNone(source)
                self.assertTrue(source.startswith(
                    "{# Make sure to avoid 4-spaces-deep (or deeper) "
                    "indentation #}"))

                # process_yaml_for_expansion is not called
                self.assertEqual(mock_process_yaml.call_count, 0)


class ParseDateSpecTest(SingleCourseTestMixin, TestCase):
    # test content.parse_date_spec

    mock_now_value = mock.MagicMock()

    def setUp(self):
        super().setUp()

        fake_now = mock.patch("course.content.now")
        self.mock_now = fake_now.start()
        self.mock_now.return_value = self.mock_now_value
        self.addCleanup(fake_now.stop)

        self.vctx = mock.MagicMock()
        self.mock_add_warning = mock.MagicMock()
        self.mock_add_warning.return_value = None
        self.vctx.add_warning = self.mock_add_warning

    def test_datespec_is_none(self):
        datespec = None
        course = self.course
        self.assertIsNone(content.parse_date_spec(course, datespec))

    def test_course_is_none_not_parsed(self):
        datespec = "homework_due 1 + 25 hours"
        time = datetime.datetime(2018, 12, 30, 23, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        course = None
        self.assertEqual(
            content.parse_date_spec(course, datespec), self.mock_now_value)

    def test_course_is_none_parsed(self):
        # this also tested datespec is datetime
        course = None
        datespec = datetime.datetime(2018, 12, 30, 23, tzinfo=pytz.UTC)
        self.assertEqual(
            content.parse_date_spec(course, datespec, self.vctx), datespec)
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_datespec_is_datetime(self):
        # when tzinfo is None
        datespec = datetime.datetime(2018, 12, 30, 23).replace(tzinfo=None)
        from relate.utils import localize_datetime
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, self.vctx),
            localize_datetime(datespec))

    def test_datespec_is_date(self):
        # when tzinfo is None
        datespec = datetime.date(2018, 12, 30)
        from relate.utils import localize_datetime
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, self.vctx),
            localize_datetime(datetime.datetime(2018, 12, 30, tzinfo=None)))

    def test_datespec_date_str(self):
        datespec = "2038-01-01"
        from relate.utils import localize_datetime
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, self.vctx),
            localize_datetime(datetime.datetime(2038, 1, 1)))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_not_parsed(self):
        datespec = "foo + bar"
        self.assertEqual(
            content.parse_date_spec(self.course, datespec), self.mock_now_value)

    def test_at_time(self):
        datespec = "homework_due 1 @ 23:59"

        from relate.utils import localize_datetime
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=localize_datetime(datetime.datetime(2019, 1, 1)))
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            localize_datetime(datetime.datetime(2019, 1, 1, 23, 59)))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_at_time_hour_invalid(self):
        datespec = "homework_due 1 @ 24:59"
        with self.assertRaises(content.InvalidDatespec):
            content.parse_date_spec(self.course, datespec, vctx=self.vctx)

    def test_at_time_minute_invalid(self):
        datespec = "homework_due 1 @ 20:62"
        with self.assertRaises(content.InvalidDatespec):
            content.parse_date_spec(self.course, datespec, vctx=self.vctx)

    def test_plus(self):
        datespec = "homework_due 1 + 25 hours"

        # event not defined, no vctx
        self.assertEqual(
            content.parse_date_spec(self.course, datespec), self.mock_now_value)

        # event not defined, with vctx
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            self.mock_now_value)
        expected_warning_msg = ("Unrecognized date/time specification: '%s' "
                                "(interpreted as 'now'). "
                                "You should add an event with this name." % datespec)

        self.assertEqual(self.mock_add_warning.call_count, 1)
        self.assertIn(expected_warning_msg, self.mock_add_warning.call_args[0])
        self.mock_add_warning.reset_mock()

        # event defined
        time = datetime.datetime(2018, 12, 30, 23, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_minus(self):
        datespec = "homework_due 1 - 25 hours"

        time = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2018, 12, 30, 23, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_plus_days(self):
        datespec = "homework_due 1 + 1 day"

        time = datetime.datetime(2018, 12, 31, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_plus_weeks(self):
        datespec = "homework_due 1 + 2 weeks"

        time = datetime.datetime(2018, 12, 31, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2019, 1, 14, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_plus_minutes(self):
        datespec = "homework_due 1 +     2 hour - 59 minutes"

        time = datetime.datetime(2018, 12, 31, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2018, 12, 31, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)

    def test_plus_invalid_time_unit(self):
        datespec = "homework_due 1 + 2 foos"

        time = datetime.datetime(2018, 12, 31, tzinfo=pytz.UTC)
        factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)
        from course.validation import ValidationError
        with self.assertRaises(ValidationError) as cm:
            content.parse_date_spec(self.course, datespec, vctx=self.vctx)

        expected_error_msg = "invalid identifier '%s'" % datespec
        self.assertIn(expected_error_msg, str(cm.exception))

        # no vctx
        self.assertEqual(
            content.parse_date_spec(self.course, datespec), self.mock_now_value)

    def test_is_end(self):
        datespec = "end:homework_due 1 + 25 hours"

        time = datetime.datetime(2018, 12, 30, 23, tzinfo=pytz.UTC)
        evt = factories.EventFactory(
            course=self.course, kind="homework_due", ordinal=1,
            time=time)

        # event has no end_time, no vctx
        self.assertEqual(
            content.parse_date_spec(self.course, datespec),
            datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC))

        # event has no end_time, no vctx
        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 1)
        expected_warning_msg = (
            "event '%s' has no end time, using start time instead"
            % datespec)
        self.assertIn(expected_warning_msg, self.mock_add_warning.call_args[0])
        self.mock_add_warning.reset_mock()

        # update event with end_time
        evt.time -= datetime.timedelta(days=1)
        evt.end_time = time
        evt.save()

        self.assertEqual(
            content.parse_date_spec(self.course, datespec, vctx=self.vctx),
            datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(self.mock_add_warning.call_count, 0)


class GetCourseDescTest(SingleCourseTestMixin, HackRepoMixin, TestCase):
    # test content.get_course_desc and content.get_processed_page_chunks

    fake_commit_sha = "my_fake_commit_sha_for_course_desc"

    def test_shown(self):
        resp = self.c.get(self.course_page_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Welcome to the sample course")

        # test that markup_to_html is called
        self.assertContains(resp, "course/test-course/flow/quiz-test/start/")

    def test_not_shown(self):
        resp = self.c.get(self.course_page_url)
        self.assertNotContains(
            resp, "Welcome to the computer-based testing facility")

    @override_settings(RELATE_FACILITIES={
        "test_center": {
            "ip_ranges": ["192.168.100.0/24"],
            "exams_only": False}, })
    def test_show_in_fake_facility(self):
        data = {
            "facilities": ["test_center"],
            "custom_facilities": [],
            "add_pretend_facilities_header": ["on"],
            "set": ''}

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # pretend facility
            self.post_set_pretend_facilities(data=data)

            resp = self.c.get(self.course_page_url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Welcome to the sample course")
            self.assertContains(
                resp, "Welcome to the computer-based testing facility")

    def test_shown_with_empty_chunk_rule(self):
        self.course.active_git_commit_sha = self.fake_commit_sha
        self.course.save()

        resp = self.c.get(self.course_page_url)
        self.assertContains(resp, "empty rules")

    def test_visible_for_role(self):
        self.course.active_git_commit_sha = self.fake_commit_sha
        self.course.save()

        resp = self.c.get(self.course_page_url)
        self.assertNotContains(resp, "Shown to instructor")

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.course_page_url)
            self.assertContains(resp, "Shown to instructor")

    def test_weight_higher_shown_first(self):
        self.course.active_git_commit_sha = self.fake_commit_sha
        self.course.save()

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.course_page_url)

            shown_to_instructor = "Shown to instructor"  # weight 100

            # wight: 50 before 2018-1-1, after that, 200
            display_order = "Display order"

            self.assertContains(resp, shown_to_instructor)
            self.assertContains(resp, display_order)

            response_text = resp.content.decode()

            shown_to_instructor_idx = response_text.index(shown_to_instructor)
            display_order_idx = response_text.index(display_order)
            self.assertGreater(shown_to_instructor_idx, display_order_idx)

            # fake time to 2017-12-31
            set_fake_time_data = {
                "time": datetime.datetime(2017, 12, 31).strftime("%Y-%m-%d %H:%M"),
                "set": ''}
            self.post_set_fake_time(data=set_fake_time_data)

            # second visit
            resp = self.c.get(self.course_page_url)
            response_text = resp.content.decode()

            shown_to_instructor_idx = response_text.index(shown_to_instructor)
            display_order_idx = response_text.index(display_order)
            self.assertGreater(display_order_idx, shown_to_instructor_idx)


class GetFlowPageDescTest(SingleCoursePageTestMixin, TestCase):
    # test content.get_flow_desc

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.flow_desc = cls.get_hacked_flow_desc()

    def test_success(self):
        self.assertEqual(
            content.get_flow_page_desc(
                flow_id=self.flow_id,
                flow_desc=self.flow_desc,
                group_id="intro",
                page_id="welcome").id, "welcome")

        self.assertEqual(
            content.get_flow_page_desc(
                flow_id=self.flow_id,
                flow_desc=self.flow_desc,
                group_id="quiz_tail",
                page_id="addition").id, "addition")

    def test_flow_page_desc_does_not_exist(self):
        with self.assertRaises(ObjectDoesNotExist):
            content.get_flow_page_desc(
                self.flow_id, self.flow_desc, "quiz_start", "unknown_page")

        with self.assertRaises(ObjectDoesNotExist):
            content.get_flow_page_desc(
                self.flow_id, self.flow_desc, "unknown_group", "unknown_page")


class NormalizeFlowDescTest(SingleCoursePageTestMixin, TestCase):
    # content.normalize_flow_desc
    def test_success_no_rules(self):
        # this also make sure normalize_flow_desc without flow_desc.rule
        # works correctly
        flow_desc = self.get_hacked_flow_desc(del_rules=True)
        self.assertTrue(
            content.normalize_flow_desc(
                flow_desc=flow_desc), flow_desc)


class MarkupToHtmlTest(SingleCoursePageTestMixin, TestCase):
    # content.markup_to_html
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = self.instructor_participation.user

        from course.utils import CoursePageContext
        self.pctx = CoursePageContext(request, self.course.identifier)

    def test_link_fixer_works(self):
        with self.pctx.repo as repo:
            text = "[this course](course:)"
            self.assertEqual(content.markup_to_html(
                self.course, repo, self.course.active_git_commit_sha, text),
                '<p><a href="%s">this course</a></p>' % self.course_page_url)

    def test_startswith_jinja_prefix(self):
        with self.pctx.repo as repo:
            text = "   [JINJA][this course](course:)"
            self.assertEqual(content.markup_to_html(
                self.course, repo,
                self.course.active_git_commit_sha.encode(), text),
                '<p><a href="%s">this course</a></p>' % self.course_page_url)

    @override_settings()
    def test_disable_codehilite_not_configured(self):
        # if RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION is not configured,
        # the default value is True
        del settings.RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION
        with self.pctx.repo as repo:
            text = "[this course](course:)"
            with mock.patch("markdown.markdown") as mock_markdown:
                mock_markdown.return_value = "some text"
                content.markup_to_html(
                    self.course, repo,
                    self.course.active_git_commit_sha.encode(), text)

                self.assertEqual(mock_markdown.call_count, 1)
                used_extensions = mock_markdown.call_args[1]["extensions"]
                self.assertNotIn(
                    "markdown.extensions.codehilite(css_class=highlight)",
                    used_extensions)

    @override_settings(RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=True)
    def test_disable_codehilite_configured_true(self):
        with self.pctx.repo as repo:
            text = "[this course](course:)"
            with mock.patch("markdown.markdown") as mock_markdown:
                mock_markdown.return_value = "some text"
                content.markup_to_html(
                    self.course, repo,
                    self.course.active_git_commit_sha.encode(), text)

                self.assertEqual(mock_markdown.call_count, 1)
                used_extensions = mock_markdown.call_args[1]["extensions"]
                self.assertNotIn(
                    "markdown.extensions.codehilite(css_class=highlight)",
                    used_extensions)

    @override_settings(RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION=False)
    def test_disable_codehilite_configured_false(self):
        with self.pctx.repo as repo:
            text = "[this course](course:)"
            with mock.patch("markdown.markdown") as mock_markdown:
                mock_markdown.return_value = "some text"
                content.markup_to_html(
                    self.course, repo,
                    self.course.active_git_commit_sha.encode(), text)

                self.assertEqual(mock_markdown.call_count, 1)
                used_extensions = mock_markdown.call_args[1]["extensions"]
                self.assertIn(
                    "markdown.extensions.codehilite(css_class=highlight)",
                    used_extensions)


class GetFlowPageClassTest(SingleCourseTestMixin, TestCase):
    # test content.get_flow_page_class

    def get_pctx(self, commit_sha=None):
        if commit_sha is not None:
            self.course.active_git_commit_sha = commit_sha
            self.course.save()
            self.course.refresh_from_db()

        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = self.instructor_participation.user

        from course.utils import CoursePageContext
        return CoursePageContext(request, self.course.identifier)

    def test_built_in_class(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        self.assertEqual(
            content.get_flow_page_class(repo, "TextQuestion", commit_sha),
            page.TextQuestion)

    def test_class_not_found_dot_path_length_1(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        with self.assertRaises(content.ClassNotFoundError):
            content.get_flow_page_class(repo, "UnknownClass", commit_sha)

    def test_class_not_found_module_not_exist(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        with self.assertRaises(content.ClassNotFoundError):
            content.get_flow_page_class(
                repo, "mypackage.UnknownClass", commit_sha)

    def test_class_not_found_module_does_not_exist(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        with self.assertRaises(content.ClassNotFoundError):
            content.get_flow_page_class(
                repo, "mypackage.UnknownClass", commit_sha)

    def test_class_not_found_last_component_does_not_exist(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        with self.assertRaises(content.ClassNotFoundError):
            content.get_flow_page_class(
                repo, "tests.resource.UnknownClass", commit_sha)

    def test_found_by_dotted_path(self):
        repo = mock.MagicMock()
        commit_sha = mock.MagicMock()
        from tests.resource import MyFakeQuestionType
        self.assertEqual(
            content.get_flow_page_class(
                repo, "tests.resource.MyFakeQuestionType", commit_sha),
            MyFakeQuestionType)


class ListFlowIdsTest(unittest.TestCase):
    # test content.list_flow_ids
    def setUp(self):
        fake_get_repo_blob = mock.patch("course.content.get_repo_blob")
        self.mock_get_repo_blob = fake_get_repo_blob.start()
        self.addCleanup(fake_get_repo_blob.stop)
        self.repo = mock.MagicMock()
        self.commit_sha = mock.MagicMock()

    def test_object_does_not_exist(self):
        self.mock_get_repo_blob.side_effect = ObjectDoesNotExist()
        self.assertEqual(content.list_flow_ids(self.repo, self.commit_sha), [])

    def test_result(self):
        tree = Tree()
        tree.add(b"not_a_flow.txt", stat.S_IFREG, b"not a flow")
        tree.add(b"flow_b.yml", stat.S_IFREG, b"flow_b content")
        tree.add(b"flow_a.yml", stat.S_IFREG, b"flow_a content")
        tree.add(b"flow_c.yml", stat.S_IFREG, b"flow_c content")
        tree.add(b"temp_dir", stat.S_IFDIR, b"a temp dir")

        self.mock_get_repo_blob.return_value = tree

        self.assertEqual(content.list_flow_ids(
            self.repo, self.commit_sha), ["flow_a", "flow_b", "flow_c"])

# vim: fdm=marker
