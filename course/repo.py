from __future__ import annotations


__copyright__ = "Copyright (C) 2025 University of Illinois Board of Trustees"

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

import os
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias, cast

import dulwich.objects
import dulwich.repo
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.utils.translation import gettext as _
from typing_extensions import override


if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType


def _get_cache_key_root():
    # Not bumping the cache key for semantically-significant model updates has
    # potentially catastrophic consequences, since stale/invalid models
    # will get pulled from the model cache without warning. In addition to being
    # catastrophic, these failures will also be puzzling, because they are
    # not connected to *just* currently-running code. As a result, this
    # takes a very belt-and-supenders approach to constructing a cache
    # key that changes whenever the code changes.

    pieces: list[str] = ["6"]

    from pytools import find_module_git_revision
    git_rev = find_module_git_revision(__file__, 1)
    if git_rev is not None:
        pieces.append(git_rev[:7])

    hash = sha256()
    count = 0
    for p in Path(__file__).parent.glob("*.py"):
        count += 1
        hash.update(p.read_bytes())
    if count < 25:
        raise RuntimeError("cache key computation did not find enough source files")
    pieces.append(hash.hexdigest()[:7])

    # Why limit pieces to seven characters, you ask? Memcache has a key length limit
    # of 250 characters, so we've got to be somewhat conservative. 16**-7 is 3e-9,
    # square that: I can live with that failure probability.
    # https://stackoverflow.com/q/1125806

    return "-".join(pieces)


CACHE_KEY_ROOT = _get_cache_key_root()


# {{{ repo-ish types

class SubdirRepoWrapper:
    repo: dulwich.repo.Repo
    subdir: str

    def __init__(self, repo: dulwich.repo.Repo, subdir: str) -> None:
        self.repo = repo

        # This wrapper should only get used if there is a subdir to be had.
        assert subdir
        self.subdir = subdir

    def controldir(self) -> Path | str:
        return self.repo.controldir()

    def close(self) -> None:
        self.repo.close()

    def __enter__(self) -> SubdirRepoWrapper:
        return self

    def __exit__(self,
                exc_type: type[Exception],
                exc_val: Exception,
                exc_tb: TracebackType) -> None:
        self.close()

    def get_refs(self) -> Mapping[bytes, bytes]:
        return self.repo.get_refs()

    def __setitem__(self, item: bytes, value: bytes) -> None:
        self.repo[item] = value

    def __delitem__(self, item: bytes) -> None:
        del self.repo[item]


# }}}


class EmptyRepo:
    def controldir(self):
        return None

    def close(self):
        pass

    def __getitem__(self, obj_id: object):
        raise KeyError(obj_id)

    @override
    def __str__(self):
        return "<EMPTYREPO>"

    def decode(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self,
                exc_type: type[Exception],
                exc_val: Exception,
                exc_tb: TracebackType) -> None:
        self.close()


class FileSystemFakeRepo:
    root: Path

    def __init__(self, root: Path):
        assert isinstance(root, Path)
        self.root = root

    def close(self):
        pass

    def controldir(self):
        return self.root

    def __getitem__(self,
                obj_id: FileSystemFakeRepoFile | FileSystemFakeRepoTree | bytes
            ):
        if isinstance(obj_id, bytes):
            # too much effort to ensure this via type checking
            raise ValueError("FileSystemFakeRepo received a bytes obj_id")
        return obj_id

    @override
    def __str__(self):
        return f"<FS FAKEREPO:{self.root}>"

    def decode(self):
        return self

    @property
    def tree(self):
        return FileSystemFakeRepoTree(self.root)

    def __enter__(self):
        return self

    def __exit__(self,
                exc_type: type[Exception],
                exc_val: Exception,
                exc_tb: TracebackType) -> None:
        self.close()


@dataclass(frozen=True)
class FileSystemFakeRepoTreeEntry:  # pragma: no cover
    path: bytes
    mode: int


class FileSystemFakeRepoTree:
    root: Path

    def __init__(self, root: Path):
        if not isinstance(root, Path):
            root = Path(root)
        self.root = root

    def __getitem__(self, name: bytes):
        if not name:
            raise KeyError("<empty filename>")

        path = self.root / name.decode()

        if not path.exists():
            raise KeyError(path)

        from os import stat
        from stat import S_ISDIR
        stat_result = stat(path)
        # returns mode, "sha"
        if S_ISDIR(stat_result.st_mode):
            return stat_result.st_mode, FileSystemFakeRepoTree(path)
        else:
            return stat_result.st_mode, FileSystemFakeRepoFile(path)

    def items(self) -> list[FileSystemFakeRepoTreeEntry]:
        import os
        return [
                FileSystemFakeRepoTreeEntry(
                    path=n.encode(),
                    mode=os.stat(full_name).st_mode)
                for n in os.listdir(self.root)
                # dead symlinks get listed but do not 'exist'/can't be stat'ed
                if os.path.exists(full_name := os.path.join(self.root, n))]


class FileSystemFakeRepoFile:
    name: Path

    def __init__(self, name: Path):
        if not isinstance(name, Path):
            name = Path(name)
        self.name = name

    @property
    def data(self):
        try:
            return self.name.read_bytes()
        except FileNotFoundError as e:
            raise ObjectDoesNotExist(self.name) from e


Repo_ish: TypeAlias = (dulwich.repo.Repo
    | SubdirRepoWrapper
    | FileSystemFakeRepo
    | EmptyRepo)
Blob_ish: TypeAlias = dulwich.objects.Blob | FileSystemFakeRepoFile
Tree_ish: TypeAlias = dulwich.objects.Tree | FileSystemFakeRepoTree
RevisionID_ish: TypeAlias = dulwich.objects.ObjectID


def _look_up_git_object(
            repo: dulwich.repo.Repo | FileSystemFakeRepo,
            root_tree: dulwich.objects.Tree | FileSystemFakeRepoTree,
            full_name: str,
            _max_symlink_depth: int | None = None
        ) -> Tree_ish | Blob_ish:
    """Traverse git directory tree from *root_tree*, respecting symlinks."""

    if _max_symlink_depth is None:
        _max_symlink_depth = 20
    if _max_symlink_depth == 0:
        raise ObjectDoesNotExist(_("symlink nesting depth exceeded "
            "while locating '%s'") % full_name)

    # https://github.com/inducer/relate/pull/556
    # FIXME: https://github.com/inducer/relate/issues/767
    name_parts = os.path.normpath(full_name).split(os.sep)

    processed_name_parts: list[str] = []

    cur_lookup: Tree_ish | Blob_ish = root_tree

    from stat import S_ISLNK

    while name_parts:
        if not isinstance(cur_lookup, Tree_ish):
            raise ObjectDoesNotExist(
                    _("'%s' is not a directory, cannot lookup nested names")
                    % os.sep.join(processed_name_parts))

        name_part = name_parts.pop(0)

        if not name_part:
            # tolerate empty path components (begrudgingly)
            continue
        elif name_part == ".":
            continue

        encoded_name_part = name_part.encode()
        try:
            mode_sha = cur_lookup[encoded_name_part]
        except KeyError:
            raise ObjectDoesNotExist(_("resource '%s' not found") % full_name)

        mode, cur_lookup_sha = mode_sha

        if S_ISLNK(mode):
            if isinstance(repo, dulwich.repo.Repo):
                assert isinstance(cur_lookup_sha, bytes)
                link_data = cast("dulwich.objects.Blob", repo[cur_lookup_sha]).data
                assert isinstance(link_data, bytes)
            elif isinstance(repo, FileSystemFakeRepo):
                # The filesystem will have resolved these behind our back.
                raise AssertionError()
            link_target = os.sep.join([*processed_name_parts, link_data.decode()])
            cur_lookup = _look_up_git_object(repo, root_tree, link_target,
                    _max_symlink_depth=_max_symlink_depth-1)
        else:
            processed_name_parts.append(name_part)
            if isinstance(repo, dulwich.repo.Repo):
                assert isinstance(cur_lookup_sha, bytes)
                lkup = repo[cur_lookup_sha]
                assert isinstance(lkup, Tree_ish | Blob_ish)
            elif isinstance(repo, FileSystemFakeRepo):
                assert isinstance(cur_lookup_sha,
                                  (FileSystemFakeRepoTree, FileSystemFakeRepoFile))
                lkup = repo[cur_lookup_sha]

            cur_lookup = lkup

    return cur_lookup


def get_true_repo_and_path(
            repo: Repo_ish,
            path: str
        ) -> tuple[dulwich.repo.Repo | FileSystemFakeRepo | EmptyRepo, str]:
    while isinstance(repo, SubdirRepoWrapper):
        if path:
            path = f"{repo.subdir}/{path}"
        else:
            path = repo.subdir

        repo = repo.repo

    return repo, path


def get_repo_tree(
            repo: Repo_ish,
            full_name: str,
            commit_sha: RevisionID_ish) -> Tree_ish:
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    :arg allow_tree: Allow the resulting object to be a directory
    """

    dul_repo, full_name = get_true_repo_and_path(repo, full_name)

    if isinstance(dul_repo, FileSystemFakeRepo):
        return FileSystemFakeRepoTree(dul_repo.root / full_name)
    if isinstance(dul_repo, EmptyRepo):
        raise ObjectDoesNotExist(full_name)

    try:
        commit_obj = dul_repo[commit_sha]
    except KeyError:
        raise ObjectDoesNotExist(
                _("commit sha '%s' not found") % commit_sha.decode())
    assert isinstance(commit_obj, dulwich.objects.Commit)
    tree_sha = commit_obj.tree

    tree_obj = dul_repo[tree_sha]
    assert isinstance(tree_obj, dulwich.objects.Tree)

    git_obj = _look_up_git_object(
            dul_repo, root_tree=tree_obj, full_name=full_name)

    from dulwich.objects import Tree

    msg_full_name = full_name or _("(repo root)")

    if isinstance(git_obj, Tree | FileSystemFakeRepoTree):
        return git_obj
    else:
        raise ObjectDoesNotExist(_("resource '%s' is not a tree") % msg_full_name)


def get_repo_blob(
            repo: Repo_ish,
            full_name: str,
            commit_sha: RevisionID_ish
        ) -> Blob_ish:
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    :arg allow_tree: Allow the resulting object to be a directory
    """
    dul_repo, full_name = get_true_repo_and_path(repo, full_name)

    if isinstance(dul_repo, FileSystemFakeRepo):
        return FileSystemFakeRepoFile(Path(full_name))
    if isinstance(dul_repo, EmptyRepo):
        raise ObjectDoesNotExist("empty repository")

    try:
        commit_obj = dul_repo[commit_sha]
    except KeyError:
        assert commit_sha
        raise ObjectDoesNotExist(
                _("commit sha '%s' not found") % commit_sha.decode())

    assert isinstance(commit_obj, dulwich.objects.Commit)
    tree_sha = commit_obj.tree
    tree_obj = dul_repo[tree_sha]
    assert isinstance(tree_obj, dulwich.objects.Tree)

    git_obj = _look_up_git_object(
            dul_repo, root_tree=tree_obj, full_name=full_name)

    from dulwich.objects import Blob

    msg_full_name = full_name or _("(repo root)")

    if isinstance(git_obj, Blob | FileSystemFakeRepoFile):
        return git_obj
    else:
        raise ObjectDoesNotExist(_("resource '%s' is not a file") % msg_full_name)


def get_repo_blob_data_cached(
        repo: Repo_ish, full_name: str, commit_sha: RevisionID_ish) -> bytes:
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(commit_sha, bytes):
        from urllib.parse import quote_plus
        cache_key: str | None = "%s%R%1".join((
            CACHE_KEY_ROOT,
            quote_plus(str(repo.controldir())),
            quote_plus(full_name),
            commit_sha.decode(),
            ".".join(str(s) for s in sys.version_info[:2]),
            ))
    else:
        cache_key = None

    try:
        import django.core.cache as cache
    except ImproperlyConfigured:
        cache_key = None

    result: bytes | None = None
    if cache_key is None:
        result = get_repo_blob(repo, full_name, commit_sha).data
        assert isinstance(result, bytes)
        return result

    # Byte string is wrapped in a tuple to force pickling because memcache's
    # python wrapper appears to auto-decode/encode string values, thus trying
    # to decode our byte strings. Grr.

    def_cache = cache.caches["default"]  # pyright: ignore[reportPossiblyUnboundVariable]

    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        cached_result = def_cache.get(cache_key)

        if cached_result is not None:
            (result,) = cached_result
            assert isinstance(result, bytes), cache_key
            return result

    result = get_repo_blob(repo, full_name, commit_sha).data
    assert result is not None

    from django.conf import settings
    if len(result) <= getattr(settings, "RELATE_CACHE_MAX_BYTES", 0):
        def_cache.add(cache_key, (result,), None)

    assert isinstance(result, bytes)

    return result
