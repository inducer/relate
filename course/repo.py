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

import posixpath
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, TypeAlias, cast

import dulwich.objects
import dulwich.repo
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.utils.translation import gettext as _
from typing_extensions import Self, override


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
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


# {{{ content repository interface

class NoRevisionNeeded:
    pass


RevisionID_ish: TypeAlias = dulwich.objects.ObjectID | type[NoRevisionNeeded]


@dataclass(frozen=True)
class RepoTreeEntry:
    path: bytes
    mode: int


class RepoBlob(ABC):
    @property
    @abstractmethod
    def data(self) -> bytes:
        raise NotImplementedError


class RepoTree(ABC):
    @abstractmethod
    def lookup(self, name: bytes) -> tuple[int, RepoTree | RepoBlob]:
        """Look up a direct child, raising KeyError if it does not exist."""
        raise NotImplementedError

    @abstractmethod
    def items(self) -> Sequence[RepoTreeEntry]:
        raise NotImplementedError

    def get_entry_fingerprint(self, name: bytes) -> bytes:
        """Return an opaque content identity without following repository symlinks.

        Fingerprints may be compared across revisions of the same backend. They
        are not object handles and cannot be used to look up repository objects.
        """
        _mode, node = self.lookup(name)
        digest = sha256()
        if isinstance(node, RepoBlob):
            digest.update(b"file\\0")
            digest.update(node.data)
        else:
            digest.update(b"tree\\0")
            for entry in sorted(node.items(), key=lambda entry: entry.path):
                digest.update(len(entry.path).to_bytes(8, "big"))
                digest.update(entry.path)
                fingerprint = node.get_entry_fingerprint(entry.path)
                digest.update(len(fingerprint).to_bytes(8, "big"))
                digest.update(fingerprint)
        return digest.digest()


class Repo(ABC):
    """A revision-aware source of course files, independent of Git objects.

    Repositories own their resources unless documented otherwise. Trees return
    resolved child nodes rather than backend-specific object identifiers.
    """

    @abstractmethod
    def repo_location_hash(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        raise NotImplementedError

    @abstractmethod
    def has_revision(self, revision: RevisionID_ish) -> bool:
        """Whether this revision can be read. Unversioned sources accept any."""
        raise NotImplementedError

    def close(self) -> None:
        """Release owned resources (in-memory backends have none)."""
        return

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_val: BaseException | None,
                 exc_tb: TracebackType | None) -> None:
        self.close()

    def get_git_repo(self) -> dulwich.repo.Repo:
        """Explicit escape hatch for operations that require a Git repository."""
        raise TypeError("this repository does not support Git operations")

    def _lookup_context(self, path: str,
                        revision: RevisionID_ish) -> tuple[RepoTree, str, str]:
        """Return the traversal root, lookup path, and effective course-root path.

        Both paths are relative to the returned tree. The course-root path is
        empty when that tree is itself the course root; otherwise it bounds
        symlink traversal and makes callback targets course-relative.

        Wrappers may translate *path* and retain an enclosing tree so relative
        symlinks resolve correctly, while rejecting paths outside their root.
        """
        return self.get_root_tree(revision), path, ""

    def _cache_identity(self) -> tuple[str, str]:
        return self.repo_location_hash(), ""

    def cache_key(self) -> str:
        from urllib.parse import quote_plus
        return ":".join(quote_plus(part) for part in self._cache_identity())

    def get_tree(self, path: str, revision: RevisionID_ish) -> RepoTree:
        root, full_path, course_root = self._lookup_context(path, revision)
        node = _look_up_object(root, full_path, course_root=course_root)
        if not isinstance(node, RepoTree):
            raise ObjectDoesNotExist(_("resource '%s' is not a tree")
                                     % (path or _("(repo root)")))
        return node

    def get_blob(self, path: str, revision: RevisionID_ish, *,
                 on_symlink_target: Callable[[str], None] | None = None) -> RepoBlob:
        root, full_path, course_root = self._lookup_context(path, revision)
        node = _look_up_object(root, full_path, course_root=course_root,
                              on_symlink_target=on_symlink_target)
        if not isinstance(node, RepoBlob):
            raise ObjectDoesNotExist(_("resource '%s' is not a file")
                                     % (path or _("(repo root)")))
        return node


class GitRepo(Repo):
    git_repo: dulwich.repo.Repo

    def __init__(self, git_repo: dulwich.repo.Repo) -> None:
        self.git_repo = git_repo

    @override
    def get_git_repo(self) -> dulwich.repo.Repo:
        return self.git_repo

    @override
    def repo_location_hash(self) -> str:
        return str(self.git_repo.controldir())

    @override
    def close(self) -> None:
        self.git_repo.close()

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        if not isinstance(revision, bytes):
            return False
        try:
            return isinstance(self.git_repo[revision], dulwich.objects.Commit)
        except KeyError:
            return False

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        if not isinstance(revision, bytes):
            raise ObjectDoesNotExist("Git repositories require a revision")
        try:
            commit = self.git_repo[revision]
        except KeyError as exc:
            raise ObjectDoesNotExist(_("commit sha '%s' not found")
                                     % serialize_revision(revision)) from exc
        if not isinstance(commit, dulwich.objects.Commit):
            raise ObjectDoesNotExist("revision is not a commit")
        tree = self.git_repo[commit.tree]
        assert isinstance(tree, dulwich.objects.Tree)
        return GitRepoTree(self.git_repo, tree)


@dataclass(frozen=True)
class GitRepoBlob(RepoBlob):
    blob: dulwich.objects.Blob

    @property
    @override
    def data(self) -> bytes:
        return self.blob.data


@dataclass(frozen=True)
class GitRepoTree(RepoTree):
    repo: dulwich.repo.Repo
    tree: dulwich.objects.Tree

    @override
    def lookup(self, name: bytes) -> tuple[int, RepoTree | RepoBlob]:
        mode, oid = self.tree[name]
        obj = self.repo[oid]
        if isinstance(obj, dulwich.objects.Tree):
            return mode, GitRepoTree(self.repo, obj)
        if isinstance(obj, dulwich.objects.Blob):
            return mode, GitRepoBlob(obj)
        raise KeyError(name)

    @override
    def items(self) -> Sequence[RepoTreeEntry]:
        return [RepoTreeEntry(entry.path, entry.mode) for entry in self.tree.items()]

    @override
    def get_entry_fingerprint(self, name: bytes) -> bytes:
        return self.tree[name][1]


class SubdirRepoWrapper(Repo):
    repo: Repo
    subdir: str

    def __init__(self, repo: Repo, subdir: str) -> None:
        assert subdir
        self.repo = repo
        self.subdir = subdir

    @override
    def repo_location_hash(self) -> str:
        return self.repo.repo_location_hash()

    @override
    def _cache_identity(self) -> tuple[str, str]:
        location, parent = self.repo._cache_identity()
        return location, posixpath.join(parent, self.subdir)

    @override
    def _lookup_context(self, path: str,
                        revision: RevisionID_ish) -> tuple[RepoTree, str, str]:
        normalized = posixpath.normpath(path)
        if (posixpath.isabs(normalized) or normalized == ".."
                or normalized.startswith("../")):
            raise ObjectDoesNotExist(
                _("resource '%s' is outside the course root") % path)
        root, course_root, _parent = self.repo._lookup_context(self.subdir, revision)
        full_path = posixpath.join(course_root, path) if path else course_root
        return root, full_path, course_root

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        return self.get_tree("", revision)

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        return self.repo.has_revision(revision)

    @override
    def get_git_repo(self) -> dulwich.repo.Repo:
        return self.repo.get_git_repo()

    @override
    def close(self) -> None:
        self.repo.close()


class EmptyRepo(Repo):
    @override
    def repo_location_hash(self) -> str:
        return "none:"

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        return True

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        return OverlayRepoTree(())

# }}}

# {{{ python class repository


def attr_name_to_file_name(name: str):
    # 'Subdirectories' aka inner classes are upper case because of PEP8.
    # We can get by without upper case letters in filenames, I guess.
    name = name.lower()

    chars: list[str] = []
    i = 0
    while i < len(name):
        ch = name[i]
        if ch == "_":
            next_underscore = name.find("_", i+1)
            if next_underscore == -1:
                raise ValueError(f"lone underscore found in '{name}'")

            key = name[i+1:next_underscore]
            i = next_underscore+1

            if key == "dot":
                chars.append(".")
            else:
                raise ValueError()
        else:
            chars.append(ch)
            i += 1

    return "".join(chars)


class ProcessedRepoClass(Protocol):
    _file_name_to_attr_name: ClassVar[dict[str, str]]


class ProcessedRepoRootClass(ProcessedRepoClass, Protocol):
    registry_url: ClassVar[str]


@dataclass(frozen=True)
class PythonClassFakeRepo(Repo):
    cls: type[ProcessedRepoRootClass]

    @override
    def repo_location_hash(self) -> str:
        return f"{self.cls.__module__}:{self.cls.__qualname__}"

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        return PythonClassFakeRepoTree(self.cls)

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        return True


@dataclass(frozen=True)
class PythonClassFakeRepoTree(RepoTree):
    cls: type[ProcessedRepoClass]

    @override
    def lookup(self, name: bytes) -> tuple[int, RepoTree | RepoBlob]:
        attr = self.cls._file_name_to_attr_name.get(name.decode("utf-8"))  # pyright: ignore[reportPrivateUsage]
        if attr is None:
            raise KeyError(name)
        entry = getattr(self.cls, attr)
        if isinstance(entry, type):
            return 0o0040777, PythonClassFakeRepoTree(entry)
        return 0o666, PythonClassFakeRepoFile(entry)

    @override
    def items(self) -> Sequence[RepoTreeEntry]:
        names = (name.encode("utf-8") for name in self.cls._file_name_to_attr_name)  # pyright: ignore[reportPrivateUsage]
        return [RepoTreeEntry(name, self.lookup(name)[0]) for name in names]


@dataclass(frozen=True)
class PythonClassFakeRepoFile(RepoBlob):
    obj: object

    @property
    @override
    def data(self) -> bytes:
        if isinstance(self.obj, bytes):
            return self.obj
        assert isinstance(self.obj, str)
        return self.obj.encode("utf-8")


PYTHON_CLASS_REPO_PREFIX = "pyclass://"

PYTHON_CLASS_REPO_REGISTRY: dict[str, type[ProcessedRepoRootClass]] = {}


def _make_filename_map(cls: type[ProcessedRepoClass]) -> None:
    file_name_to_attr_name: dict[str, str] = {}
    for attr_name in dir(cls):
        if not attr_name.startswith("__"):
            file_name = attr_name_to_file_name(attr_name)
            file_name_to_attr_name[file_name] = attr_name

            entry = getattr(cls, attr_name)
            if isinstance(entry, type):
                _make_filename_map(entry)

    cls._file_name_to_attr_name = file_name_to_attr_name  # pyright: ignore[reportPrivateUsage]


def python_repo_class(cls: type) -> type[ProcessedRepoRootClass]:
    cls = cast("type[ProcessedRepoRootClass]", cls)
    key = f"{cls.__module__}:{cls.__qualname__}"
    url = f"{PYTHON_CLASS_REPO_PREFIX}{key}"
    existing_entry = PYTHON_CLASS_REPO_REGISTRY.get(key)
    if existing_entry is not None:
        assert cls is existing_entry
        return cls

    PYTHON_CLASS_REPO_REGISTRY[key] = cls
    _make_filename_map(cls)
    cls.registry_url = url
    return cls

# }}}


# {{{ filesystem repository

class FileSystemFakeRepo(Repo):
    root: Path

    def __init__(self, root: Path) -> None:
        self.root = root

    @override
    def repo_location_hash(self) -> str:
        return str(self.root)

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        if not self.root.is_dir():
            raise ObjectDoesNotExist(str(self.root))
        return FileSystemFakeRepoTree(self.root)

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        return True


@dataclass(frozen=True)
class FileSystemFakeRepoTree(RepoTree):
    root: Path

    @override
    def lookup(self, name: bytes) -> tuple[int, RepoTree | RepoBlob]:
        if not name:
            raise KeyError("<empty filename>")
        path = self.root / name.decode()
        try:
            mode = path.stat().st_mode
        except FileNotFoundError as exc:
            raise KeyError(path) from exc
        from stat import S_ISDIR
        if S_ISDIR(mode):
            return mode, FileSystemFakeRepoTree(path)
        return mode, FileSystemFakeRepoFile(path)

    @override
    def items(self) -> Sequence[RepoTreeEntry]:
        return [RepoTreeEntry(path.name.encode(), path.stat().st_mode)
                for path in self.root.iterdir() if path.exists()]


@dataclass(frozen=True)
class FileSystemFakeRepoFile(RepoBlob):
    name: Path

    @property
    @override
    def data(self) -> bytes:
        try:
            return self.name.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectDoesNotExist(self.name) from exc

# }}}


class OverlayRepo(Repo):
    """First layer wins; directories merge, unlike kinds mask later entries.

    Layers are borrowed: closing an overlay does not close its repositories.
    """

    repos: tuple[Repo, ...]

    def __init__(self, repos: Sequence[Repo]) -> None:
        self.repos = tuple(repos)

    @override
    def repo_location_hash(self) -> str:
        import json
        identities = [repo.cache_key() for repo in self.repos]
        return "overlay:" + sha256(json.dumps(identities).encode()).hexdigest()

    @override
    def get_root_tree(self, revision: RevisionID_ish) -> RepoTree:
        return OverlayRepoTree(tuple(
            repo.get_tree("", revision) for repo in self.repos))

    @override
    def has_revision(self, revision: RevisionID_ish) -> bool:
        return all(repo.has_revision(revision) for repo in self.repos)


@dataclass(frozen=True)
class OverlayRepoTree(RepoTree):
    layers: tuple[RepoTree, ...]

    @override
    def lookup(self, name: bytes) -> tuple[int, RepoTree | RepoBlob]:
        from stat import S_ISDIR
        directories: list[RepoTree] = []
        directory_mode = 0
        for tree in self.layers:
            try:
                mode, obj = tree.lookup(name)
            except KeyError:
                continue
            if S_ISDIR(mode):
                assert isinstance(obj, RepoTree)
                if not directories:
                    directory_mode = mode
                directories.append(obj)
            elif not directories:
                return mode, obj
        if directories:
            return directory_mode, OverlayRepoTree(tuple(directories))
        raise KeyError(name)

    @override
    def items(self) -> Sequence[RepoTreeEntry]:
        names = {entry.path for tree in self.layers for entry in tree.items()}
        return [RepoTreeEntry(name, self.lookup(name)[0]) for name in sorted(names)]


_NO_REVISION_TAG = "NOREV_AKJDLFKSJFDLKSJDFLKSJDFLJSF"


def serialize_revision(rev: RevisionID_ish) -> str:
    if isinstance(rev, type):
        return _NO_REVISION_TAG
    else:
        return rev.decode()


def deserialize_revision(serialized_rev: str) -> RevisionID_ish:
    if serialized_rev == _NO_REVISION_TAG:
        return NoRevisionNeeded

    return dulwich.objects.ObjectID(serialized_rev.encode())


def _look_up_object(
            root_tree: RepoTree,
            full_name: str,
            _max_symlink_depth: int | None = None,
            *,
            on_symlink_target: Callable[[str], None] | None = None,
            course_root: str = "",
        ) -> RepoTree | RepoBlob:
    """Traverse a content tree, reporting complete course-relative symlink targets.

    The callback runs for every hop, including intermediate links and directory
    links with their unconsumed suffix, before the target is looked up.
    """

    if _max_symlink_depth is None:
        _max_symlink_depth = 20
    if _max_symlink_depth == 0:
        raise ObjectDoesNotExist(_("symlink nesting depth exceeded "
            "while locating '%s'") % full_name)

    # https://github.com/inducer/relate/pull/556
    # FIXME: https://github.com/inducer/relate/issues/767
    # Git paths use POSIX separators, regardless of the host operating system.
    name_parts = posixpath.normpath(full_name).split("/")

    processed_name_parts: list[str] = []

    cur_lookup: RepoTree | RepoBlob = root_tree

    from stat import S_ISLNK

    while name_parts:
        if not isinstance(cur_lookup, RepoTree):
            raise ObjectDoesNotExist(
                    _("'%s' is not a directory, cannot lookup nested names")
                    % "/".join(processed_name_parts))

        name_part = name_parts.pop(0)

        if not name_part:
            # tolerate empty path components (begrudgingly)
            continue
        elif name_part == ".":
            continue

        encoded_name_part = name_part.encode()
        try:
            mode, child = cur_lookup.lookup(encoded_name_part)
        except KeyError:
            raise ObjectDoesNotExist(_("resource '%s' not found") % full_name)

        if S_ISLNK(mode):
            assert isinstance(child, RepoBlob)
            link_data = child.data

            try:
                target = link_data.decode()
            except UnicodeDecodeError as exc:
                raise ObjectDoesNotExist(_("invalid symlink target")) from exc
            if not target or "\x00" in target:
                raise ObjectDoesNotExist(_("invalid symlink target"))
            if posixpath.isabs(target):
                raise ObjectDoesNotExist(_("absolute symlink target is not allowed"))
            link_target = posixpath.normpath(posixpath.join(
                *processed_name_parts, target, *name_parts))
            relative_target = posixpath.relpath(link_target, course_root or ".")
            if (relative_target == ".."
                    or relative_target.startswith("../")):
                raise ObjectDoesNotExist(_("symlink target is outside the course root"))
            if on_symlink_target is not None:
                on_symlink_target(relative_target)
            # Restart with the complete target path, including any remaining
            # suffix, so later relative links use their actual containing directory.
            return _look_up_object(
                root_tree, link_target,
                _max_symlink_depth=_max_symlink_depth-1,
                on_symlink_target=on_symlink_target, course_root=course_root)
        else:
            processed_name_parts.append(name_part)
            cur_lookup = child

    return cur_lookup


def get_repo_cache_key(repo: Repo) -> str:
    return repo.cache_key()


def get_repo_tree(repo: Repo, full_name: str, commit_sha: RevisionID_ish) -> RepoTree:
    return repo.get_tree(full_name, commit_sha)


def get_repo_blob(repo: Repo, full_name: str, commit_sha: RevisionID_ish, *,
                  on_symlink_target: Callable[[str], None] | None = None) -> RepoBlob:
    return repo.get_blob(full_name, commit_sha, on_symlink_target=on_symlink_target)


def get_repo_blob_data_cached(
        repo: Repo, full_name: str, commit_sha: RevisionID_ish) -> bytes:
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(commit_sha, bytes):
        from urllib.parse import quote_plus
        cache_key: str | None = "%s%R%1".join((
            CACHE_KEY_ROOT,
            get_repo_cache_key(repo),
            quote_plus(full_name),
            commit_sha.decode(),
            ".".join(str(s) for s in sys.version_info[:2]),
            ))
    else:
        cache_key = None

    try:
        from django.core import cache
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
