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

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile, InMemoryUploadedFile
from unittest import skipUnless

from course.page.upload import FileUploadForm, JupyterNotebookUploadForm

from tests.base_test_mixins import SingleCourseQuizPageTestMixin, HackRepoMixin
from tests.test_sandbox import SingleCoursePageSandboxTestBaseMixin
from tests.constants import PAGE_ERRORS
from tests.utils import may_run_expensive_tests, SKIP_EXPENSIVE_TESTS_REASON

UPLOAD_WITH_NEGATIVE_MAXIMUM_SIZE_MARKDOWN = """
type: FileUploadQuestion
id: test
value: 5
maximum_megabytes: -0.5
prompt: |

    # Upload a pdf file

mime_types:

    - application/pdf

rubric: |

    uploaded?

"""

UPLOAD_WITH_NEGATIVE_VALUE_MARKDOWN = """
type: FileUploadQuestion
id: test
value: -5
maximum_megabytes: 0.5
prompt: |

    # Upload a pdf file

mime_types:

    - application/pdf

rubric: |

    uploaded?

"""

UPLOAD_WITHOUT_VALUE_MARKDOWN = """
type: FileUploadQuestion
id: test
maximum_megabytes: 0.5
prompt: |

    # Upload a pdf file

mime_types:

    - application/pdf

rubric: |

    uploaded?

"""

UPLOAD_WITH_UNKNOWN_MIME_TYPES_MARKDOWN = """
type: FileUploadQuestion
id: test
value: 5
maximum_megabytes: 0.5
prompt: |

    # Upload a file

mime_types:

    - application/pdf
    - application/unknown

rubric: |

    uploaded?

"""

UPLOAD_WITH_SMALL_MAX_ALLOWED_SIZE = """
type: FileUploadQuestion
id: test
maximum_megabytes: 0.0001
value: 1
prompt: |

    # Upload a pdf file

mime_types:

    - application/pdf

rubric: |

    uploaded?

"""

UPLOAD_JUPYTER_NOTEBOOK = """
type: JupyterNotebookUploadQuestion
id: jupyter_sandbox
access_rules:
    add_permissions:
        - change_answer
value: 5
maximum_megabytes: 0.5
prompt: |
    # Upload your favorite JupterNotebook file
rubric: |
    Have they uploaded an .ipynb file?
"""


class FileUploadQuestionSandBoxTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    def test_size_validation(self):
        markdown = UPLOAD_WITH_NEGATIVE_MAXIMUM_SIZE_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "'maximum_megabytes' expects a positive value, "
            "got -0.5 instead")

    def test_negative_value(self):
        markdown = UPLOAD_WITH_NEGATIVE_VALUE_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "sandboxAttribute 'value' expects a non-negative value, "
            "got -5 instead")

    def test_mime_types(self):
        markdown = UPLOAD_WITH_UNKNOWN_MIME_TYPES_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "unrecognized mime types 'application/unknown'")

    def test_no_value(self):
        markdown = UPLOAD_WITHOUT_VALUE_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, "upload question does not have assigned point value")

    def test_upload_file_with_size_exceed(self):
        markdown = UPLOAD_WITH_SMALL_MAX_ALLOWED_SIZE
        from tests.constants import TEST_PDF_FILE_PATH
        with open(TEST_PDF_FILE_PATH, 'rb') as fp:
            answer_data = {"uploaded_file": fp}
            resp = self.get_page_sandbox_submit_answer_response(
                markdown,
                answer_data=answer_data)
            self.assertFormErrorLoose(resp, "Please keep file size under")
            self.assertFormErrorLoose(resp, "Current filesize is")

    def test_upload_jupyter_notebook(self):
        # This makes sure upload jupyter notebook works in sandbox
        markdown = UPLOAD_JUPYTER_NOTEBOOK
        from tests.constants import TEST_JUPYTER_NOTEBOOK_FILE_PATH
        with open(TEST_JUPYTER_NOTEBOOK_FILE_PATH, 'rb') as fp:
            answer_data = {"uploaded_file": fp}
            resp = self.get_page_sandbox_submit_answer_response(
                markdown,
                answer_data=answer_data)
            self.assertFormErrorLoose(resp, None)


@skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class UploadQuestionNormalizeTest(SingleCourseQuizPageTestMixin,
                                  HackRepoMixin, TestCase):
    def test_two_mime_types_normalize(self):
        self.course.active_git_commit_sha = (
            "my_fake_commit_sha_for_normalized_bytes_answer")
        self.course.save()

        self.start_flow(self.flow_id)

        self.submit_page_answer_by_page_id_and_test(
            page_id="proof", do_grading=True, do_human_grade=True,
            ensure_download_after_grading=True, dl_file_extension=".dat")


class FileUploadFormTest(TestCase):
    def test_form_valid(self):

        upload_form = FileUploadForm(
            maximum_megabytes=0.1,
            mime_types=["text/plain"],
            data={},
            files={'uploaded_file': SimpleUploadedFile('name', b'some content')})
        self.assertTrue(upload_form.is_valid(), upload_form.errors)

    def test_form_invalid(self):
        upload_form = FileUploadForm(
            maximum_megabytes=0.1,
            mime_types=["application/pdf"],
            data={},
            files={'uploaded_file': SimpleUploadedFile('name', b'some content')})
        self.assertFalse(upload_form.is_valid())


class JupyterNotebookUploadFormTest(TestCase):
    def test_form_valid(self):
        from tests.constants import TEST_JUPYTER_NOTEBOOK_FILE_PATH
        from io import BytesIO
        with open(TEST_JUPYTER_NOTEBOOK_FILE_PATH, 'rb') as fp:
            buf = fp.read()
        nbfile = InMemoryUploadedFile(
            BytesIO(buf),
            field_name="uploaded_file",
            name="my_file", content_type="application/x-ipynb+json",
            size=0.5, charset=None)
        upload_form = JupyterNotebookUploadForm(
            maximum_megabytes=0.1,
            mime_types=["application/x-ipynb+json"],
            data={},
            files={'uploaded_file': nbfile})
        self.assertTrue(upload_form.is_valid(), upload_form.errors)

    def test_form_invalid(self):
        upload_form = JupyterNotebookUploadForm(
            maximum_megabytes=0.1,
            mime_types=["application/x-ipynb+json"],
            data={},
            files={'uploaded_file': SimpleUploadedFile('name', b'some content')})
        self.assertFalse(upload_form.is_valid())

# vim: fdm=marker
