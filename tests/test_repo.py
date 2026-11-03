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
from unittest.mock import patch

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.test import override_settings
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from pydantic import TypeAdapter

from course import content
from course.repo import (
    SubdirRepoWrapper,
    get_repo_blob,
    get_repo_blob_data_cached,
    get_repo_tree,
    get_true_repo_and_path,
)
from course.validation import ValidationContext


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


@pytest.mark.parametrize("cache_kind", ["blob", "raw_yaml", "model"])
@override_settings(
    CACHES={"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "repo-course-root-tests",
    }},
    RELATE_CACHE_MAX_BYTES=1024,
)
def test_repo_caches_distinguish_course_roots(tmp_path: Path, cache_kind: str):
    with Repo.init_bare(tmp_path) as repo:
        root = Tree()
        root_blob = Blob.from_string(b"title: root\n")
        repo.object_store.add_object(root_blob)
        root.add(b"course.yml", 0o100644, root_blob.id)
        for subdir in ["first", "second"]:
            blob = Blob.from_string(f"title: {subdir}\n".encode())
            tree = Tree()
            tree.add(b"course.yml", 0o100644, blob.id)
            repo.object_store.add_object(blob)
            repo.object_store.add_object(tree)
            root.add(subdir.encode(), 0o040000, tree.id)

        commit = Commit()
        commit.tree = root.id
        commit.author = commit.committer = b"Test <test@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Test cache isolation between course roots"
        repo.object_store.add_object(root)
        repo.object_store.add_object(commit)

        model_ta = TypeAdapter(dict[str, str])
        with patch("course.repo.get_repo_blob", wraps=get_repo_blob) as get_blob:
            for _ in range(2):
                for subdir in ["", "first", "second"]:
                    course_repo = SubdirRepoWrapper(repo, subdir) if subdir else repo
                    title = subdir or "root"
                    if cache_kind == "blob":
                        result = get_repo_blob_data_cached(
                            course_repo, "course.yml", commit.id)
                        assert result == f"title: {title}\n".encode()
                    elif cache_kind == "raw_yaml":
                        result = content.get_raw_yaml_from_repo(
                            course_repo, "course.yml", commit.id)
                        assert result == {"title": title}
                    else:
                        result = content.get_model_from_repo(
                            ValidationContext(course_repo, commit.id),
                            model_ta, course_repo, "course.yml", commit.id)
                        assert result == {"title": title}

            # Each root is read once, then served from its own cache entry.
            assert get_blob.call_count == 3
