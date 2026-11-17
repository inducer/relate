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

from stat import S_ISDIR
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.test import override_settings
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo as DulwichRepo

from course.repo import (
    EmptyRepo,
    FileSystemFakeRepo,
    GitRepo,
    NoRevisionNeeded,
    OverlayRepo,
    OverlayRepoTree,
    PythonClassFakeRepo,
    Repo,
    get_repo_blob,
    get_repo_blob_data_cached,
    get_repo_cache_key,
    get_repo_tree,
    python_repo_class,
)


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from dulwich.objects import ObjectID


@python_repo_class
class Upper:
    shared = "upper"
    blocked = "file masks directory"

    class Merged:
        shared = "upper nested"
        upper = "upper only"

        class Deep:
            upper = "deep upper"

    class Directory:
        child = "directory masks file"


@python_repo_class
class Lower:
    shared = "lower"
    lower = "lower only"
    directory = "masked file"

    class Blocked:
        child = "masked child"

    class Merged:
        shared = "lower nested"
        lower = "lower nested only"

        class Deep:
            lower = "deep lower"


def _write_files(root: Path, files: dict[str, str]) -> FileSystemFakeRepo:
    root.mkdir()
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    return FileSystemFakeRepo(root)


@pytest.fixture(params=["python", "filesystem", "mixed"])
def overlay(request: pytest.FixtureRequest, tmp_path: Path) -> OverlayRepo:
    upper: Repo = PythonClassFakeRepo(Upper)
    lower: Repo = PythonClassFakeRepo(Lower)
    if request.param in {"filesystem", "mixed"}:
        upper = _write_files(tmp_path / "upper", {
            "shared": "upper",
            "blocked": "file masks directory",
            "merged/shared": "upper nested",
            "merged/upper": "upper only",
            "merged/deep/upper": "deep upper",
            "directory/child": "directory masks file",
        })
    if request.param == "filesystem":
        lower = _write_files(tmp_path / "lower", {
            "shared": "lower",
            "lower": "lower only",
            "directory": "masked file",
            "blocked/child": "masked child",
            "merged/shared": "lower nested",
            "merged/lower": "lower nested only",
            "merged/deep/lower": "deep lower",
        })
    return OverlayRepo([upper, lower])


def test_non_git_backends_do_not_emulate_git_objects(tmp_path: Path):
    filesystem = _write_files(tmp_path / "repo", {"file": "content"})
    python_repo = PythonClassFakeRepo(Upper)
    overlay = OverlayRepo([python_repo, filesystem])
    for repo in [python_repo, filesystem, EmptyRepo(), overlay]:
        assert isinstance(repo, Repo)
        assert not hasattr(repo, "__getitem__")
        assert not hasattr(repo, "decode")
        assert not hasattr(repo, "tree")
    for repo in [python_repo, filesystem, overlay]:
        tree = repo.get_tree("", NoRevisionNeeded)
        assert not hasattr(tree, "__getitem__")
        assert all(isinstance(entry.path, bytes) for entry in tree.items())


def test_overlay_precedence_and_recursive_merge(overlay: OverlayRepo):
    for name, expected in {
        "shared": b"upper",
        "lower": b"lower only",
        "merged/shared": b"upper nested",
        "merged/upper": b"upper only",
        "merged/lower": b"lower nested only",
        "merged/deep/upper": b"deep upper",
        "merged/deep/lower": b"deep lower",
        "directory/child": b"directory masks file",
    }.items():
        assert get_repo_blob(overlay, name, NoRevisionNeeded).data == expected

    root = get_repo_tree(overlay, "", NoRevisionNeeded)
    assert isinstance(root, OverlayRepoTree)
    assert {entry.path for entry in root.items()} == {
        b"shared", b"lower", b"blocked", b"merged", b"directory"}
    assert {entry.path: S_ISDIR(entry.mode) for entry in root.items()} == {
        b"shared": False, b"lower": False, b"blocked": False,
        b"merged": True, b"directory": True,
    }
    merged = get_repo_tree(overlay, "merged/deep", NoRevisionNeeded)
    assert {entry.path for entry in merged.items()} == {b"upper", b"lower"}
    with pytest.raises(ObjectDoesNotExist):
        overlay.get_blob("missing", NoRevisionNeeded)


@pytest.mark.parametrize("name", ["missing", "merged/missing", "blocked/child"])
def test_overlay_missing_and_masked_paths(overlay: OverlayRepo, name: str):
    for lookup in [get_repo_blob, get_repo_tree]:
        with pytest.raises(ObjectDoesNotExist):
            lookup(overlay, name, NoRevisionNeeded)


@pytest.mark.parametrize("name", ["shared", "blocked", "merged/shared"])
def test_overlay_file_is_not_tree(overlay: OverlayRepo, name: str):
    with pytest.raises(ObjectDoesNotExist, match="not a tree"):
        get_repo_tree(overlay, name, NoRevisionNeeded)


@pytest.mark.parametrize("name", ["", "merged", "directory"])
def test_overlay_directory_is_not_blob(overlay: OverlayRepo, name: str):
    with pytest.raises(ObjectDoesNotExist, match="not a file"):
        get_repo_blob(overlay, name, NoRevisionNeeded)


def test_empty_and_nested_overlays():
    for repo in [OverlayRepo([]), OverlayRepo([EmptyRepo()])]:
        assert not get_repo_tree(repo, "", NoRevisionNeeded).items()
        with pytest.raises(ObjectDoesNotExist):
            get_repo_blob(repo, "missing", NoRevisionNeeded)
    repo = OverlayRepo([OverlayRepo([PythonClassFakeRepo(Upper)]),
                        PythonClassFakeRepo(Lower)])
    assert get_repo_blob(repo, "shared", NoRevisionNeeded).data == b"upper"
    assert get_repo_blob(repo, "merged/lower", NoRevisionNeeded).data == (
        b"lower nested only")


def test_directory_merge_ignores_intermediate_file(tmp_path: Path):
    bottom = _write_files(tmp_path / "bottom", {"directory/bottom": "bottom"})
    repo = OverlayRepo([PythonClassFakeRepo(Upper), PythonClassFakeRepo(Lower),
                        bottom])
    assert get_repo_blob(repo, "directory/child", NoRevisionNeeded).data == (
        b"directory masks file")
    assert get_repo_blob(repo, "directory/bottom", NoRevisionNeeded).data == b"bottom"


def test_overlay_cache_identity(overlay: OverlayRepo):
    upper, lower = overlay.repos
    key = get_repo_cache_key(overlay)
    assert key == get_repo_cache_key(OverlayRepo([upper, lower]))
    assert key != get_repo_cache_key(OverlayRepo([lower, upper]))
    assert key != get_repo_cache_key(OverlayRepo([upper]))
    assert key != get_repo_cache_key(upper)


@override_settings(
    CACHES={"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "overlay-repo-tests",
    }},
    RELATE_CACHE_MAX_BYTES=1024,
)
def test_overlay_blob_cache_isolation():
    from django.core.cache import cache
    from dulwich.objects import ObjectID

    cache.clear()
    upper, lower = PythonClassFakeRepo(Upper), PythonClassFakeRepo(Lower)
    repos = [OverlayRepo([upper, lower]), OverlayRepo([lower, upper]), upper]
    # Fake repos need no revision, but accept a bytes revision to exercise caching.
    revision = ObjectID(b"a" * 40)
    with patch("course.repo.get_repo_blob", wraps=get_repo_blob) as lookup:
        for _ in range(2):
            for repo, expected in zip(
                    repos, [b"upper", b"lower", b"upper"], strict=True):
                assert get_repo_blob_data_cached(repo, "shared", revision) == expected
        assert lookup.call_count == 3


def test_overlay_no_revision_reads_live_files(tmp_path: Path):
    layer = _write_files(tmp_path / "live", {"file": "before"})
    repo = OverlayRepo([layer])
    assert get_repo_blob_data_cached(repo, "file", NoRevisionNeeded) == b"before"
    (layer.root / "file").write_text("after")
    assert get_repo_blob_data_cached(repo, "file", NoRevisionNeeded) == b"after"


def test_filesystem_rooted_lookup_and_validation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _write_files(tmp_path / "repo", {"file": "rooted", "dir/child": "child"})
    (tmp_path / "file").write_text("wrong working directory")
    monkeypatch.chdir(tmp_path)
    assert get_repo_blob(repo, "file", NoRevisionNeeded).data == b"rooted"
    assert get_repo_blob(repo, "dir/child", NoRevisionNeeded).data == b"child"
    tree = get_repo_tree(repo, "dir", NoRevisionNeeded)
    assert {entry.path for entry in tree.items()} == {b"child"}
    for lookup in [get_repo_blob, get_repo_tree]:
        for name in ["missing", "file/child"]:
            with pytest.raises(ObjectDoesNotExist):
                lookup(repo, name, NoRevisionNeeded)
    with pytest.raises(ObjectDoesNotExist, match="not a tree"):
        get_repo_tree(repo, "file", NoRevisionNeeded)
    with pytest.raises(ObjectDoesNotExist, match="not a file"):
        get_repo_blob(repo, "dir", NoRevisionNeeded)
    with pytest.raises(ObjectDoesNotExist):
        get_repo_tree(FileSystemFakeRepo(tmp_path / "missing"), "", NoRevisionNeeded)


def test_git_layer_and_symlink(tmp_path: Path):
    with DulwichRepo.init_bare(tmp_path) as git_repo:
        blob = Blob.from_string(b"git fallback")
        link = Blob.from_string(b"shared")
        tree = Tree()
        tree.add(b"fallback", 0o100644, blob.id)
        tree.add(b"link", 0o120000, link.id)
        tree.add(b"shared", 0o100644, blob.id)
        commit = Commit()
        commit.tree = tree.id
        commit.author = commit.committer = b"Test <test@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Overlay layer"
        for obj in [blob, link, tree, commit]:
            git_repo.object_store.add_object(obj)
        repo = OverlayRepo([
            EmptyRepo(), PythonClassFakeRepo(Upper), GitRepo(git_repo)])
        assert repo.has_revision(commit.id)
        assert not repo.has_revision(b"0" * 40)
        assert not repo.has_revision(NoRevisionNeeded)
        assert get_repo_blob(repo, "shared", commit.id).data == b"upper"
        assert get_repo_blob(repo, "fallback", commit.id).data == b"git fallback"
        targets: list[str] = []
        assert get_repo_blob(repo, "link", commit.id,
                             on_symlink_target=targets.append).data == b"upper"
        assert targets == ["shared"]


@pytest.fixture(params=[False, True], ids=["flat", "nested"])
def symlink_overlay(
        request: pytest.FixtureRequest,
        tmp_path: Path) -> Iterator[tuple[OverlayRepo, ObjectID]]:
    override = _write_files(tmp_path / "override", {
        "nested/final/answer": "overlay answer",
        "final/answer": "wrong alias-relative answer",
    })
    git_path = tmp_path / "git"
    git_path.mkdir()
    with DulwichRepo.init_bare(git_path) as git_repo:
        files = {
            "chain": (0o120000, b"middle/link"),
            "middle/link": (0o120000, b"../shared"),
            "shared": (0o100644, b"masked git answer"),
            "portal": (0o120000, b"nested/real"),
            "nested/real/relative": (0o120000, b"../final/answer"),
            "nested/final/answer": (0o100644, b"masked git answer"),
            "merged-link": (0o120000, b"merged"),
            "blocked-link": (0o120000, b"blocked/child"),
            "blocked/child": (0o100644, b"masked git child"),
            "shared-link": (0o120000, b"directory"),
            "directory": (0o100644, b"masked git file"),
            "absolute": (0o120000, b"/shared"),
            "escape": (0o120000, b"../shared"),
            "invalid": (0o120000, b"\xff"),
            "empty": (0o120000, b""),
            # "nul" would resolve to a device in the Windows filesystem layer.
            "embedded-nul": (0o120000, b"shared\x00"),
            "dangling": (0o120000, b"missing"),
            "cycle": (0o120000, b"cycle"),
        }
        trees = {"": Tree()}
        for path, (mode, data) in files.items():
            parts = path.split("/")
            for length in range(1, len(parts)):
                trees.setdefault("/".join(parts[:length]), Tree())
            blob = Blob.from_string(data)
            git_repo.object_store.add_object(blob)
            trees["/".join(parts[:-1])].add(parts[-1].encode(), mode, blob.id)
        for path in sorted(trees, key=lambda name: (name.count("/"), bool(name)),
                           reverse=True):
            tree = trees[path]
            if path:
                parent, _, name = path.rpartition("/")
                trees[parent].add(name.encode(), 0o040000, tree.id)
            git_repo.object_store.add_object(tree)
        commit = Commit()
        commit.tree = trees[""].id
        commit.author = commit.committer = b"Test <test@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Overlay symlinks"
        git_repo.object_store.add_object(commit)
        layers: list[Repo] = [PythonClassFakeRepo(Upper), GitRepo(git_repo)]
        if request.param:
            layers = [OverlayRepo(layers)]
        yield OverlayRepo([override, *layers]), commit.id


@pytest.mark.parametrize(("path", "expected", "expected_targets"), [
    ("chain", b"upper", ["middle/link", "shared"]),
    ("portal/relative", b"overlay answer",
     ["nested/real/relative", "nested/final/answer"]),
])
def test_overlay_symlink_hops_use_overlay_root(
        symlink_overlay: tuple[OverlayRepo, ObjectID],
        path: str, expected: bytes, expected_targets: list[str]):
    repo, revision = symlink_overlay
    targets: list[str] = []
    assert get_repo_blob(repo, path, revision,
                         on_symlink_target=targets.append).data == expected
    assert targets == expected_targets


def test_overlay_symlink_callback_can_deny_later_hop(
        symlink_overlay: tuple[OverlayRepo, ObjectID]):
    repo, revision = symlink_overlay
    targets: list[str] = []

    def authorize(target: str) -> None:
        targets.append(target)
        if target == "shared":
            raise PermissionDenied("denied target")

    with pytest.raises(PermissionDenied, match="denied target"):
        get_repo_blob(repo, "chain", revision, on_symlink_target=authorize)
    assert targets == ["middle/link", "shared"]


def test_overlay_symlink_targets_obey_masking(
        symlink_overlay: tuple[OverlayRepo, ObjectID]):
    repo, revision = symlink_overlay
    tree = get_repo_tree(repo, "merged-link", revision)
    assert {entry.path for entry in tree.items()} == {b"shared", b"upper", b"deep"}
    assert get_repo_blob(repo, "shared-link/child", revision).data == (
        b"directory masks file")
    with pytest.raises(ObjectDoesNotExist, match="not a directory"):
        get_repo_blob(repo, "blocked-link", revision)
    with pytest.raises(ObjectDoesNotExist, match="not a file"):
        get_repo_blob(repo, "shared-link", revision)


@pytest.mark.parametrize(("path", "message", "expected_targets"), [
    ("absolute", "absolute symlink", []),
    ("escape", "outside the course root", []),
    ("invalid", "invalid symlink target", []),
    ("empty", "invalid symlink target", []),
    ("embedded-nul", "invalid symlink target", []),
    ("dangling", "not found", ["missing"]),
    ("cycle", "symlink nesting depth exceeded", ["cycle"] * 20),
])
def test_overlay_symlink_errors(
        symlink_overlay: tuple[OverlayRepo, ObjectID],
        path: str, message: str, expected_targets: list[str]):
    repo, revision = symlink_overlay
    targets: list[str] = []
    with pytest.raises(ObjectDoesNotExist, match=message):
        get_repo_blob(repo, path, revision, on_symlink_target=targets.append)
    assert targets == expected_targets
