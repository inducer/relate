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
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import Http404
from django.test import override_settings
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from pydantic import TypeAdapter

from course import content, views
from course.constants import ParticipationPermission as PPerm
from course.models import Course
from course.repo import (
    SubdirRepoWrapper,
    get_repo_blob,
    get_repo_blob_data_cached,
    get_repo_tree,
    get_true_repo_and_path,
)
from course.validation import ValidationContext


if TYPE_CHECKING:
    from collections.abc import Iterator
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


@pytest.fixture
def repo_file_git(tmp_path: Path) -> Iterator[tuple[Repo, bytes]]:
    files = {
        ".attributes.yml": (0o100644, b"""access_if_has_role:
  student: ["allowed*.txt"]
  in_exam: ["exam*.txt"]
"""),
        "allowed.txt": (0o120000, b"target/allowed.txt"),
        "allowed-denied.txt": (0o120000, b"target/denied.txt"),
        "denied.txt": (0o120000, b"target/allowed.txt"),
        "allowed-chain.txt": (0o120000, b"middle/denied.txt"),
        "allowed-chain-ok.txt": (0o120000, b"middle/allowed.txt"),
        "allowed-noattrs.txt": (0o120000, b"unmarked/file.txt"),
        "exam-link.txt": (0o120000, b"target/allowed.txt"),
        "exam-ok.txt": (0o120000, b"target/exam.txt"),
        "portal": (0o120000, b"nested/real"),
        "allowed-cycle.txt": (0o120000, b"allowed-cycle.txt"),
        "allowed-absolute.txt": (0o120000, b"/target/allowed.txt"),
        "allowed-invalid.txt": (0o120000, b"\xff"),
        "allowed-empty.txt": (0o120000, b""),
        "allowed-nul.txt": (0o120000, b"target/allowed.txt\x00"),
        "allowed-dangling.txt": (0o120000, b"target/allowed-missing.txt"),
        "nested/escape.txt": (0o120000, b"../target/allowed.txt"),
        "nested/escape-dir": (0o120000, b"../target"),
        "nested/local.txt": (0o120000, b"real/file.txt"),
        "target/.attributes.yml": (0o100644, b"""access_if_has_role:
  student: ["allowed*.txt"]
  in_exam: ["exam.txt"]
"""),
        "target/allowed.txt": (0o100644, b"authorized target\n"),
        "target/denied.txt": (0o100644, b"secret target\n"),
        "target/exam.txt": (0o100644, b"exam resource\n"),
        "middle/.attributes.yml": (
            0o100644, b'access_if_has_role: {student: ["allowed*.txt"]}\n'),
        "middle/denied.txt": (0o120000, b"../target/allowed.txt"),
        "middle/allowed.txt": (0o120000, b"../target/allowed.txt"),
        "unmarked/file.txt": (0o100644, b"no attributes\n"),
        "unmarked/link.txt": (0o120000, b"../target/allowed.txt"),
        "nested/real/.attributes.yml": (
            0o100644, b'access_if_has_role: {student: ["*.txt"]}\n'),
        "nested/real/file.txt": (0o100644, b"directory resource\n"),
        "nested/real/relative.txt": (0o120000, b"../final/allowed.txt"),
        "nested/final/.attributes.yml": (
            0o100644, b'access_if_has_role: {student: ["allowed*.txt"]}\n'),
        "nested/final/allowed.txt": (0o100644, b"physical relative target\n"),
        # A resolver using the alias directory would serve this instead.
        "final/.attributes.yml": (
            0o100644, b'access_if_has_role: {student: ["allowed*.txt"]}\n'),
        "final/allowed.txt": (0o100644, b"wrong relative target\n"),
    }
    with Repo.init_bare(tmp_path) as repo:
        trees = {"": Tree()}
        for path, (mode, data) in files.items():
            parent, _, name = path.rpartition("/")
            blob = Blob.from_string(data)
            repo.object_store.add_object(blob)
            trees.setdefault(parent, Tree()).add(name.encode(), mode, blob.id)
            while parent:
                parent = parent.rpartition("/")[0]
                trees.setdefault(parent, Tree())

        for path in sorted(trees, key=lambda path: path.count("/"),
                           reverse=True):
            if not path:
                continue
            parent, _, name = path.rpartition("/")
            repo.object_store.add_object(trees[path])
            trees.setdefault(parent, Tree()).add(
                name.encode(), 0o040000, trees[path].id)
        repo.object_store.add_object(trees[""])
        commit = Commit()
        commit.tree = trees[""].id
        commit.author = commit.committer = b"Test <test@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Repository file authorization fixtures"
        repo.object_store.add_object(commit)
        yield repo, commit.id


@pytest.fixture
def repo_file_view(
        repo_file_git: tuple[Repo, bytes],
        ) -> Iterator[tuple[MagicMock, Course, bytes]]:
    repo, commit_sha = repo_file_git
    course = Course(pk=1, identifier="repo-test")
    request = MagicMock()
    request.method = "GET"
    request.META = {}
    request.relate_exam_lockdown = False
    request.relate_exam_lockdown_course_id = course.pk
    with (
            patch("course.views.check_course_state"),
            patch("course.views.get_course_repo", return_value=Repo(repo.path)),
            patch("course.enrollment.get_participation_permissions",
                  return_value=[(PPerm.access_files_for, "student")]),
            ):
        yield request, course, commit_sha


@pytest.mark.parametrize(("path", "expected"), [
    pytest.param("allowed-denied.txt", None, id="alias-allowed-target-denied"),
    pytest.param("denied.txt", None, id="alias-denied-target-allowed"),
    pytest.param("allowed.txt", b"authorized target\n", id="both-allowed"),
    pytest.param("allowed-chain.txt", None, id="intermediate-denied"),
    pytest.param("allowed-chain-ok.txt", b"authorized target\n", id="chain-allowed"),
    pytest.param("portal/file.txt", b"directory resource\n", id="directory-link"),
    pytest.param("portal/relative.txt", b"physical relative target\n",
                 id="relative-link-in-linked-directory"),
    pytest.param("allowed-noattrs.txt", None, id="target-missing-attributes"),
    pytest.param("unmarked/link.txt", None, id="alias-missing-attributes"),
])
def test_repo_file_backend_symlink_access(
        repo_file_view: tuple[MagicMock, Course, bytes],
        path: str, expected: bytes | None):
    request, course, commit_sha = repo_file_view
    if expected is None:
        with pytest.raises(PermissionDenied):
            views.get_repo_file_backend(request, course, None, commit_sha, path)
    else:
        response = views.get_repo_file_backend(request, course, None, commit_sha, path)
        assert response.status_code == 200
        assert response.content == expected
        assert response["Content-Type"] == "text/plain"


@pytest.mark.parametrize(("path", "expected"), [
    pytest.param("allowed.txt", None, id="exam-denies-student-alias"),
    pytest.param("exam-link.txt", None, id="exam-denies-student-target"),
    pytest.param("exam-ok.txt", b"exam resource\n", id="exam-allows-both"),
])
def test_repo_file_backend_symlink_exam_access(
        repo_file_view: tuple[MagicMock, Course, bytes],
        path: str, expected: bytes | None):
    request, course, commit_sha = repo_file_view
    request.relate_exam_lockdown = True
    with patch("course.enrollment.get_participation_permissions") as permissions:
        if expected is None:
            with pytest.raises(PermissionDenied):
                views.get_repo_file_backend(request, course, None, commit_sha, path)
        else:
            response = views.get_repo_file_backend(
                request, course, None, commit_sha, path)
            assert response.status_code == 200
            assert response.content == expected
        permissions.assert_not_called()


@pytest.mark.parametrize("endpoint", ["revision", "current"])
@pytest.mark.parametrize("allowed", [False, True])
def test_repo_file_endpoints_enforce_symlink_access(
        repo_file_view: tuple[MagicMock, Course, bytes],
        endpoint: str, allowed: bool):
    request, course, commit_sha = repo_file_view
    path = "allowed.txt" if allowed else "allowed-denied.txt"
    with (
            patch("course.views.get_object_or_404", return_value=course),
            patch("course.views.get_participation_for_request", return_value=None),
            patch("course.content.get_course_commit_sha", return_value=commit_sha),
            ):
        def get_response():
            if endpoint == "revision":
                return views.get_repo_file(
                    request, course.identifier, commit_sha.decode(), path)
            return views.get_current_repo_file(request, course.identifier, path)

        if allowed:
            response = get_response()
            assert response.status_code == 200
            assert response.content == b"authorized target\n"
        else:
            with pytest.raises(PermissionDenied):
                get_response()


@pytest.mark.parametrize("path", [
    "allowed-cycle.txt", "allowed-absolute.txt", "allowed-invalid.txt",
    "allowed-empty.txt", "allowed-nul.txt", "allowed-dangling.txt",
])
def test_repo_file_invalid_symlink(
        repo_file_view: tuple[MagicMock, Course, bytes], path: str):
    request, course, commit_sha = repo_file_view
    with pytest.raises(Http404):
        views.get_repo_file_backend(request, course, None, commit_sha, path)


@pytest.mark.parametrize("is_tree", [False, True])
def test_symlink_cannot_escape_course_root(
        repo_file_git: tuple[Repo, bytes], is_tree: bool):
    repo, commit_sha = repo_file_git
    wrapped = SubdirRepoWrapper(repo, "nested")
    lookup = get_repo_tree if is_tree else get_repo_blob
    path = "escape-dir" if is_tree else "escape.txt"
    with pytest.raises(ObjectDoesNotExist, match="outside the course root"):
        lookup(wrapped, path, commit_sha)


def test_symlink_callback_uses_course_relative_paths(
        repo_file_git: tuple[Repo, bytes]):
    repo, commit_sha = repo_file_git
    targets = []
    blob = get_repo_blob(
        SubdirRepoWrapper(repo, "nested"), "local.txt", commit_sha,
        on_symlink_target=targets.append)
    assert blob.data == b"directory resource\n"
    assert targets == ["real/file.txt"]


def test_warm_blob_cache_does_not_skip_target_authorization(
        repo_file_git: tuple[Repo, bytes],
        repo_file_view: tuple[MagicMock, Course, bytes]):
    repo, commit_sha = repo_file_git
    assert get_repo_blob_data_cached(
        repo, "allowed-denied.txt", commit_sha) == b"secret target\n"
    request, course, commit_sha = repo_file_view
    with pytest.raises(PermissionDenied):
        views.get_repo_file_backend(
            request, course, None, commit_sha, "allowed-denied.txt")
