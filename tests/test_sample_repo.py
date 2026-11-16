from __future__ import annotations


__copyright__ = "Copyright (C) 2026 University of Illinois Board of Trustees"

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

from pathlib import Path

import pytest

from course.repo import (
    NoRevisionNeeded,
    PythonClassFakeRepo,
    get_repo_blob,
    get_repo_tree,
)
from tests.sample_repo import SAMPLE_ROOT, SampleCourse, get_revision_overlay


@pytest.mark.parametrize("filename", [
    "course.yml", "flows/quiz-test.yml", "images/django-logo.png", "pdfs/sample.pdf",
])
def test_sample_snapshot_preserves_bytes(filename: str):
    repo = PythonClassFakeRepo(SampleCourse)
    assert get_repo_blob(repo, filename, NoRevisionNeeded).data == (
        SAMPLE_ROOT / filename).read_bytes()


def test_named_revision_overlay():
    from tests.constants import FAKED_YAML_PATH

    first = get_revision_overlay(b"my_fake_commit_sha_1")
    second = get_revision_overlay(b"my_fake_commit_sha_2")

    for repo, filename in [(first, "fake-quiz-test1.yml"),
                           (second, "fake-quiz-test2.yml")]:
        assert get_repo_blob(repo, "flows/quiz-test.yml", NoRevisionNeeded).data == (
            Path(FAKED_YAML_PATH) / filename).read_bytes()
        assert get_repo_blob(repo, "images/django-logo.png", NoRevisionNeeded).data == (
            SAMPLE_ROOT / "images/django-logo.png").read_bytes()
        tree = get_repo_tree(repo, "flows", NoRevisionNeeded)
        assert b"exam-1.yml" in {entry.path for entry in tree.items()}
