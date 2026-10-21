from __future__ import annotations

import sys
from functools import wraps
from importlib import import_module, reload
from io import StringIO
from typing import TYPE_CHECKING
from unittest import mock  # ruff:ignore[unused-import]

from django.conf import settings
from django.urls import clear_url_caches

from course.models import Course
from course.repo import NoRevisionNeeded, serialize_revision
from course.versioning import create_course_with_repo_path


if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from course.repo import ProcessedRepoRootClass


class suppress_stdout_decorator:  # ruff:ignore[invalid-class-name]
    def __init__(self, suppress_stderr=False):
        self.original_stdout = None
        self.suppress_stderr = None
        self.suppress_stderr = suppress_stderr

    def __enter__(self):
        self.original_stdout = sys.stdout
        sys.stdout = StringIO()

        if self.suppress_stderr:
            self.original_stderr = sys.stderr
            sys.stderr = StringIO()

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        if self.suppress_stderr:
            sys.stderr = self.original_stderr

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kw):
            with self:
                return func(*args, **kw)

        return wrapper


def load_url_pattern_names(patterns):
    """Retrieve a list of urlpattern names"""
    url_names = []
    for pat in patterns:
        if pat.__class__.__name__ == "RegexURLResolver":
            load_url_pattern_names(pat.url_patterns)
        elif pat.__class__.__name__ == "RegexURLPattern":
            if pat.name is not None and pat.name not in url_names:
                url_names.append(pat.name)
        else:
            from django.urls import URLPattern
            assert isinstance(pat, URLPattern)
            url_names.append(pat.name)
    return url_names


def reload_urlconf(urlconf=None):
    """Reload urlconf, this should be used when some urlpatterns are included
    according to settings
    """
    clear_url_caches()
    if urlconf is None:
        urlconf = settings.ROOT_URLCONF
    if urlconf in sys.modules:
        reload(sys.modules[urlconf])
    else:
        import_module(urlconf)


def _is_connection_psql():
    from django.db import connection
    return connection.vendor == "postgresql"


is_connection_psql = _is_connection_psql()


SKIP_NON_PSQL_REASON = "PostgreSQL specific SQL used"


def make_pyclass_course(
            cls: type[ProcessedRepoRootClass],
            owner: User,
            identifier: str = "mycourse",
        ):
    course = Course(
        identifier=identifier,
        name="My course",
        number="MY123",
        time_period="Anytime 3000",
        from_email="instructor@example.com",
        notify_email="instructor@example.com",
        git_source=cls.registry_url,
        active_git_commit_sha=serialize_revision(NoRevisionNeeded),
    )
    create_course_with_repo_path(course, owner)
    return course


# vim: fdm=marker
