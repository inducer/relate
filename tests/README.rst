Offline course fixtures
=======================

The test suite reads course content from ``resource/relate-sample``. This is a
source snapshot of https://github.com/inducer/relate-sample at commit
``004d7c72133c7cf3b53b9447479727b11610fad7`` (2026-02-26), pruned to files and
flow pages used by the tests, directly or indirectly. It contains no Git
metadata and does not need a checkout or a download when running tests.

``sample_repo.py`` exposes the snapshot through ``PythonClassFakeRepo`` for
ordinary course tests (including binary assets). Named revisions in
``constants.COMMIT_SHA_MAP`` use small checked-in YAML replacements from
``resource/faked_yamls`` over the snapshot via ``OverlayRepo``. Overlay layers
are ordered highest priority first; directories merge recursively.

Tests of Git operations instead use ``get_sample_git_repo()``. This builds a
process-local temporary Git remote with a deterministic initial commit, a
``main`` branch, and a ``subdir-repo`` branch containing the same snapshot under
``course_content/``. No Git executable or upstream history is required. Use this helper for tests that specifically need revision
existence checks, Git views, or repository updates. Git-only fixtures may use
``dulwich.repo.Repo`` directly, but wrap them in ``course.repo.GitRepo`` before
passing them to generic content APIs or ``SubdirRepoWrapper``. Use
``repo.get_git_repo()`` for Git management; ``SubdirRepoWrapper.repo`` remains a
generic ``course.repo.Repo`` rather than exposing Dulwich implicitly.

Run the ordinary suite as usual::

    uv run pytest -n 4

Network integration tests are marked ``network`` and skipped by default,
including when using ``--slow`` or ``--all``. To test an actual GitHub checkout::

    uv run pytest --network -m network tests/test_versioning.py

The SSH authentication integration test is also marked ``slow`` and requires
``--all --network`` (or ``--slow --network``). It depends on local SSH key
configuration as well as network access.

Updating the snapshot
---------------------

Export an explicitly chosen upstream revision into ``resource/relate-sample``
using ``git archive`` (not a submodule or a nested checkout). Replace the old
snapshot, remove files and flow pages unused by the tests, update the provenance
above, and run the affected tests. Keep at least one page per flow, and retain
pages exercised by generic tests that iterate over a flow's pages. Retain
indirect dependencies such as Jinja includes, question data files, and files
read by course validation.
Apart from pruning unused pages, keep test-specific content changes in source
overlays rather than modifying the retained upstream files. The snapshot is
intentionally pinned: upstream changes must not affect an ordinary test run.
