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


from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ObjectDoesNotExist
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from course.repo import (
    SubdirRepoWrapper,
    get_repo_blob,
    get_repo_tree,
    get_true_repo_and_path,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("path", [
    "../sibling/secret.txt",
    "../../sibling/secret.txt",
    "nested/../../sibling/secret.txt",
    "..",
    "nested/../..",
    "/sibling/secret.txt",
    "//sibling/secret.txt",
])
def test_subdir_repo_rejects_escape(tmp_path: Path, path: str):
    with Repo.init_bare(tmp_path) as repo:
        wrapped_repo = SubdirRepoWrapper(repo, "courses/current")
        with pytest.raises(ObjectDoesNotExist, match="outside the course root"):
            get_true_repo_and_path(wrapped_repo, path)


@pytest.mark.parametrize("path", [
    "",
    ".",
    "file.txt",
    "nested/file.txt",
    "nested/../file.txt",
    "nested//./file.txt",
])
def test_subdir_repo_accepts_relative_paths(tmp_path: Path, path: str):
    with Repo.init_bare(tmp_path) as repo:
        wrapped_repo = SubdirRepoWrapper(repo, "courses/current")
        base_repo, full_name = get_true_repo_and_path(wrapped_repo, path)
        assert base_repo is repo
        assert full_name == (f"courses/current/{path}" if path else "courses/current")


def test_subdir_repo_lookup_stays_within_course_root(tmp_path: Path):
    with Repo.init_bare(tmp_path) as repo:
        public = Blob.from_string(b"course content")
        secret = Blob.from_string(b"sibling course content")
        current = Tree()
        current.add(b"file.txt", 0o100644, public.id)
        sibling = Tree()
        sibling.add(b"secret.txt", 0o100644, secret.id)
        root = Tree()
        root.add(b"current", 0o040000, current.id)
        root.add(b"sibling", 0o040000, sibling.id)
        commit = Commit()
        commit.tree = root.id
        commit.author = commit.committer = b"Test <test@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Test course roots"
        for obj in [public, secret, current, sibling, root, commit]:
            repo.object_store.add_object(obj)

        # Verify the sibling objects exist and are readable without the wrapper.
        assert get_repo_blob(repo, "sibling/secret.txt", commit.id).data == secret.data
        assert get_repo_tree(repo, "sibling", commit.id).id == sibling.id

        wrapped_repo = SubdirRepoWrapper(repo, "current")
        assert get_repo_blob(wrapped_repo, "file.txt", commit.id).data == public.data
        assert get_repo_tree(wrapped_repo, "", commit.id).id == current.id
        assert get_repo_blob(
            wrapped_repo, "nested/../file.txt", commit.id).data == public.data

        for path in ["../sibling/secret.txt", "nested/../../sibling/secret.txt"]:
            with pytest.raises(ObjectDoesNotExist, match="outside the course root"):
                get_repo_blob(wrapped_repo, path, commit.id)
        for path in ["..", "../sibling", "nested/../../sibling"]:
            with pytest.raises(ObjectDoesNotExist, match="outside the course root"):
                get_repo_tree(wrapped_repo, path, commit.id)
