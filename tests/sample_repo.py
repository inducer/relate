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

import atexit
import tempfile
from functools import cache
from pathlib import Path

from course.repo import (
    FileSystemFakeRepo,
    OverlayRepo,
    PythonClassFakeRepo,
    python_repo_class,
)


SAMPLE_ROOT = Path(__file__).parent / "resource" / "relate-sample"


def _source_class(root: Path, name: str) -> type:
    """Expose the checked-in snapshot through the Python-class repo registry."""
    return type(name, (), {
        "__module__": __name__,
        **{
            path.name.replace(".", "_dot_"): (
                _source_class(path, path.name) if path.is_dir() else path.read_bytes())
            for path in sorted(root.iterdir())
        },
    })


SampleCourse = python_repo_class(_source_class(SAMPLE_ROOT, "SampleCourse"))
SAMPLE_SOURCE = SampleCourse.registry_url


@cache
def get_revision_overlay(revision: bytes) -> OverlayRepo:
    """Small source overlays stand in for the legacy tests' named revisions."""
    from tests.constants import COMMIT_SHA_MAP, FAKED_YAML_PATH

    root = type("Revision_" + revision.decode(), (), {"__module__": __name__})
    for filename, revisions in COMMIT_SHA_MAP.items():
        for mapping in revisions:
            if revision.decode() not in mapping:
                continue
            directory = root
            *parts, basename = filename.split("/")
            for part in parts:
                attr = part.replace(".", "_dot_")
                if not hasattr(directory, attr):
                    setattr(directory, attr, type(part, (), {}))
                directory = getattr(directory, attr)
            overlay_path = mapping[revision.decode()]["path"]
            assert isinstance(overlay_path, str)
            data = (Path(FAKED_YAML_PATH) / overlay_path).read_bytes()
            setattr(directory, basename.replace(".", "_dot_"), data)

    return OverlayRepo([
        PythonClassFakeRepo(python_repo_class(root)),
        FileSystemFakeRepo(SAMPLE_ROOT),
    ])


_git_directory: tempfile.TemporaryDirectory[str] | None = None


@cache
def get_sample_git_repo() -> Path:
    """Build a disposable Git remote locally, without Git executables or history."""
    from dulwich.objects import Blob, Commit, Tree
    from dulwich.repo import Repo

    global _git_directory
    _git_directory = tempfile.TemporaryDirectory(prefix="relate-test-git-")
    atexit.register(_git_directory.cleanup)
    path = Path(_git_directory.name)
    with Repo.init_bare(path) as repo:
        def add_tree(directory: Path):
            tree = Tree()
            for child in sorted(directory.iterdir()):
                if child.is_dir():
                    tree.add(child.name.encode(), 0o040000, add_tree(child))
                else:
                    blob = Blob.from_string(child.read_bytes())
                    repo.object_store.add_object(blob)
                    tree.add(child.name.encode(), 0o100644, blob.id)
            repo.object_store.add_object(tree)
            return tree.id

        commit = Commit()
        commit.tree = add_tree(SAMPLE_ROOT)
        commit.author = commit.committer = b"RELATE tests <tests@example.com>"
        commit.author_time = commit.commit_time = 0
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"Checked-in sample course\n"
        repo.object_store.add_object(commit)
        repo.refs[b"refs/heads/main"] = commit.id
        repo.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")

        nested_tree = Tree()
        nested_tree.add(b"course_content", 0o040000, commit.tree)
        repo.object_store.add_object(nested_tree)
        nested_commit = commit.copy()
        nested_commit.tree = nested_tree.id
        nested_commit.parents = [commit.id]
        nested_commit.message = b"Move sample course into a subdirectory\n"
        repo.object_store.add_object(nested_commit)
        repo.refs[b"refs/heads/subdir-repo"] = nested_commit.id
    return path
