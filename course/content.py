from __future__ import annotations

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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

from typing import cast, Union, Text

from django.conf import settings
from django.utils.translation import gettext as _

import os
import re
import datetime
import sys

from django.utils.timezone import now
from django.core.exceptions import ObjectDoesNotExist, ImproperlyConfigured
from django.urls import NoReverseMatch

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

import html.parser as html_parser

from jinja2 import (
        BaseLoader as BaseTemplateLoader, TemplateNotFound, FileSystemLoader)

from relate.utils import dict_to_struct, Struct, SubdirRepoWrapper
from course.constants import ATTRIBUTES_FILENAME

from yaml import safe_load as load_yaml

CACHE_KEY_ROOT = "py3"


# {{{ mypy

from typing import (  # noqa
    Any, List, Tuple, Optional, Callable, Text, Dict, FrozenSet, TYPE_CHECKING)
if TYPE_CHECKING:
    # for mypy
    from course.models import Course, Participation  # noqa
    import dulwich  # noqa
    from course.validation import ValidationContext, FileSystemFakeRepoTree  # noqa
    from course.page.base import PageBase  # noqa
    from relate.utils import Repo_ish  # noqa

Date_ish = Union[datetime.datetime, datetime.date]
Datespec = Union[datetime.datetime, datetime.date, str]


class ChunkRulesDesc(Struct):
    if_has_role: list[str]
    if_before: Datespec
    if_after: Datespec
    if_in_facility: str
    if_has_participation_tags_any: list[str]
    if_has_participation_tags_all: list[str]
    roles: list[str]
    start: Datespec
    end: Datespec
    shown: bool
    weight: float


class ChunkDesc(Struct):
    weight: float
    shown: bool
    title: str | None
    content: str
    rules: list[ChunkRulesDesc]

    html_content: str


class StaticPageDesc(Struct):
    chunks: list[ChunkDesc]
    content: str


class CourseDesc(StaticPageDesc):
    pass

# }}}


# {{{ mypy: flow start rule

class FlowSessionStartRuleDesc(Struct):
    """Rules that govern when a new session may be started and whether
    existing sessions may be listed.

    Found in the ``start`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions

    .. attribute:: if_after

        (Optional) A :ref:`datespec <datespec>` that determines a date/time
        after which this rule applies.

    .. attribute:: if_before

        (Optional) A :ref:`datespec <datespec>` that determines a date/time
        before which this rule applies.

    .. attribute:: if_has_role

        (Optional) A list of a subset of the roles defined in the course, by
        default ``unenrolled``, ``ta``, ``student``, ``instructor``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) restricting flow starting based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: if_has_in_progress_session

        (Optional) A Boolean (True/False) value, indicating that the rule only
        applies if the participant has an in-progress session.

    .. attribute:: if_has_session_tagged

        (Optional) An identifier (or ``null``) indicating that the rule only applies
        if the participant has a session with the corresponding tag.

    .. attribute:: if_has_fewer_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer
        than this number of sessions.

    .. attribute:: if_has_fewer_tagged_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer
        than this number of sessions with access rule tags.

    .. attribute:: if_signed_in_with_matching_exam_ticket

        (Optional) The rule applies if the participant signed in with an exam
        ticket matching this flow.

    .. rubric:: Rules specified

    .. attribute:: may_start_new_session

        (Mandatory) A Boolean (True/False) value indicating whether, if the
        rule applies, the participant may start a new session.

    .. attribute:: may_list_existing_sessions

        (Mandatory) A Boolean (True/False) value indicating whether, if the
        rule applies, the participant may view a list of existing sessions.

    .. attribute:: tag_session

        (Optional) An identifier that will be applied to a newly-created
        session as a "tag".  This can be used by
        :attr:`FlowSessionAccessRuleDesc.if_has_tag` and
        :attr:`FlowSessionGradingRuleDesc.if_has_tag`.

    .. attribute:: default_expiration_mode

        (Optional) One of :class:`~course.constants.flow_session_expiration_mode`.
        The expiration mode applied when a session is first created or rolled
        over.
    """

    # conditions
    if_after: Date_ish
    if_before: Date_ish
    if_has_role: list[str]
    if_has_participation_tags_any: list[str]
    if_has_participation_tags_all: list[str]
    if_in_facility: str
    if_has_in_progress_session: bool
    if_has_session_tagged: str | None
    if_has_fewer_sessions_than: int
    if_has_fewer_tagged_sessions_than: int
    if_signed_in_with_matching_exam_ticket: bool

    # rules specified
    tag_session: str | None
    may_start_new_session: bool
    may_list_existing_sessions: bool
    lock_down_as_exam_session: bool
    default_expiration_mode: str

# }}}


# {{{ mypy: flow access rule

class FlowSessionAccessRuleDesc(Struct):
    """Rules that govern what a user may do with an existing session.

    Found in the ``access`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions

    .. attribute:: if_after

        (Optional) A :ref:`datespec <datespec>` that determines a date/time
        after which this rule applies.

    .. attribute:: if_before

        (Optional) A :ref:`datespec <datespec>` that determines a date/time
        before which this rule applies.

    .. attribute:: if_started_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session
        was started before this time.

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) restricting flow access based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: if_has_tag

        (Optional) Rule applies if session has this tag (see
        :attr:`FlowSessionStartRuleDesc.tag_session`), an identifier.

    .. attribute:: if_in_progress

        (Optional) A Boolean (True/False) value. Rule applies if the session's
        in-progress status matches this Boolean value.

    .. attribute:: if_completed_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session
        was completed before this time.

    .. attribute:: if_expiration_mode

        (Optional) One of :class:`~course.constants.flow_session_expiration_mode`.
        Rule applies if the expiration mode (see :ref:`flow-life-cycle`)
        matches.

    .. attribute:: if_session_duration_shorter_than_minutes

        (Optional) The rule applies if the current session has been going on for
        less than the specified number of minutes. Fractional values (e.g. "0.5")
        are accepted here.

    .. attribute:: if_signed_in_with_matching_exam_ticket

        (Optional) The rule applies if the participant signed in with an exam
        ticket matching this flow.

    .. rubric:: Rules specified

    .. attribute:: permissions

        A list of :class:`~course.constants.flow_permission`.

        :attr:`~course.constants.flow_permission.submit_answer`
        and :attr:`~course.constants.flow_permission.end_session`
        are automatically removed from a finished (i.e. not 'in-progress')
        session.

    .. attribute:: message

        (Optional) Some text in :ref:`markup` that is shown to the student in
        an 'alert' box at the top of the page if this rule applies.
    """

    # conditions
    if_after: Date_ish
    if_before: Date_ish
    if_started_before: Date_ish
    if_has_role: list[str]
    if_has_participation_tags_any: list[str]
    if_has_participation_tags_all: list[str]
    if_in_facility: str
    if_has_tag: str | None
    if_in_progress: bool
    if_completed_before: Date_ish
    if_expiration_mode: str
    if_session_duration_shorter_than_minutes: float
    if_signed_in_with_matching_exam_ticket: bool

    # rules specified
    permissions: list
    message: str

# }}}


# {{{ mypy: flow grading rule

class FlowSessionGradingRuleDesc(Struct):
    """ Rules that govern how (permanent) grades are generated from the
    results of a flow.

    Found in the ``grading`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_started_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session
        was started before this time.

    .. attribute:: if_has_tag

        (Optional) Rule applies if session has this tag (see
        :attr:`FlowSessionStartRuleDesc.tag_session`), an identifier.

    .. attribute:: if_completed_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session
        was completed before this time.

        When evaluating this condition for in-progress sessions, the current time,
        or, if :attr:`use_last_activity_as_completion_time` is set, the time of the
        last activity is used.

        Since September 2017, this respects
        :attr:`use_last_activity_as_completion_time`.

    .. rubric:: Rules specified

    .. attribute:: credit_percent

        (Optional) A number indicating the percentage of credit assigned for
        this flow.  Defaults to 100 if not present.

    .. attribute:: due

        A :ref:`datespec <datespec>` indicating the due date of the flow. This
        is shown to the participant and also used to batch-expire 'past-due'
        flows.

    .. attribute:: generates_grade

        (Optional) A Boolean indicating whether a grade will be recorded when this
        flow is ended. Note that the value of this rule must never change over
        the lifetime of a flow. I.e. a flow that, at some point during its lifetime,
        *may* have been set to generate a grade must *always* be set to generate
        a grade. Defaults to ``true``.

    .. attribute:: use_last_activity_as_completion_time

        (Optional) A Boolean indicating whether the last time a participant made
        a change to their flow should be used as the completion time.

        Defaults to ``false`` to match past behavior. ``true`` is probably the more
        sensible value for this.

    .. attribute:: description

        (Optional) A description of this set of grading rules being applied to
        the flow.  Shown to the participant on the flow start page.

    .. attribute:: max_points

        (Optional, an integer or floating point number if given)
        The number of points on the flow which constitute
        "100% of the achievable points". If not given, this is automatically
        computed by summing point values from all constituent pages.

        This may be used to 'grade out of N points', where N is a number that
        is lower than the actually achievable count.

    .. attribute:: max_points_enforced_cap

        (Optional, an integer or floating point number if given)
        No participant will have a grade higher than this recorded for this flow.
        This may be used to limit the amount of 'extra credit' achieved beyond
        :attr:`max_points`.

    .. attribute:: bonus_points

        (Optional, an integer or floating point number if given)
        This number of points will be added to every participant's score.

    """
    # conditions
    if_has_role: list[str]
    if_has_participation_tags_any: list[str]
    if_has_participation_tags_all: list[str]
    if_started_after: Date_ish
    if_has_tag: str | None
    if_completed_before: Date_ish

    # rules specified
    credit_percent: int | float | None
    due: Date_ish
    generates_grade: bool | None
    use_last_activity_as_completion_time: bool
    description: str
    max_points: int | float | None
    max_points_enforced_cap: int | float | None
    bonus_points: int | float | None

# }}}


# {{{ mypy: flow rules

class FlowRulesDesc(Struct):
    """
    Found in the ``rules`` attribute of a :class:`FlowDesc`.

    .. attribute:: start

        Rules that govern when a new session may be started and whether
        existing sessions may be listed.

        A list of :class:`FlowSessionStartRuleDesc`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. attribute:: access

        Rules that govern what a user may do while they are interacting with an
        existing session.

        A list of :class:`FlowSessionAccessRuleDesc`.

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. rubric:: Grading-Related

    .. attribute:: grade_identifier

        (Required) The identifier of the grade to be generated once the
        participant completes the flow.  If ``null``, no grade is generated.

    .. attribute:: grade_aggregation_strategy

        (Required if :attr:`grade_identifier` is not ``null``)

        One of :class:`grade_aggregation_strategy`.

    .. attribute:: grading

        Rules that govern how (permanent) overall grades are generated from the
        results of a flow. These rules apply once a flow session ends/is submitted
        for grading. See :ref:`flow-life-cycle`.

        (Required if grade_identifier is not ``null``)
        A list of :class:`FlowSessionGradingRuleDesc`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.
    """
    start: list[FlowSessionStartRuleDesc]
    access: list[FlowSessionAccessRuleDesc]
    grading: list[FlowSessionGradingRuleDesc]
    grade_identifier: str | None
    grade_aggregation_strategy: str | None

# }}}


# {{{ mypy: flow

class FlowPageDesc(Struct):
    id: str
    type: str


class FlowPageGroupDesc(Struct):
    """
    .. attribute:: id

        (Required) A symbolic name for the page group.

    .. attribute:: pages

        (Required) A list of :ref:`flow-page`

    .. attribute:: shuffle

        (Optional) A boolean (True/False) indicating whether the order
        of pages should be as in the list :attr:`pages` or
        determined by random shuffling

    .. attribute:: max_page_count

        (Optional) An integer limiting the page count of this group
        to a certain value. Allows selection of a random subset by combining
        with :attr:`shuffle`.
    """

    id: str
    pages: list[FlowPageDesc]


class FlowDesc(Struct):
    """
    .. attribute:: title

        A plain-text title of the flow

    .. attribute:: description

        A description in :ref:`markup` shown on the start page of the flow.

    .. attribute:: completion_text

        (Optional) Some text in :ref:`markup` shown once a student has
        completed the flow.

    .. attribute:: notify_on_submit

        (Optional) A list of email addresses which to notify about a flow
        submission by a participant.

    .. attribute:: rules

        (Optional) Some rules governing students' use and grading of the flow.
        See :ref:`flow-rules`.

    .. attribute:: groups

        A list of :class:`FlowPageGroupDesc`.  Exactly one of
        :attr:`groups` or :class:`pages` must be given.

    .. attribute:: pages

        A list of :ref:`pages <flow-page>`. If you specify this, a single
        :class:`FlowPageGroupDesc` will be implicitly created. Exactly one of
        :attr:`groups` or :class:`pages` must be given.
    """

    title: str
    rules: FlowRulesDesc
    pages: list[FlowPageDesc]
    groups: list[FlowPageGroupDesc]
    notify_on_submit: list[str] | None

# }}}


# {{{ repo blob getting

def get_true_repo_and_path(repo: Repo_ish, path: str) -> tuple[dulwich.Repo, str]:

    if isinstance(repo, SubdirRepoWrapper):
        if path:
            path = repo.subdir + "/" + path
        else:
            path = repo.subdir

        return repo.repo, path

    else:
        return repo, path


def get_course_repo_path(course: Course) -> str:

    return os.path.join(settings.GIT_ROOT, course.identifier)


def get_course_repo(course: Course) -> Repo_ish:

    from dulwich.repo import Repo
    repo = Repo(get_course_repo_path(course))

    if course.course_root_path:
        return SubdirRepoWrapper(repo, course.course_root_path)
    else:
        return repo


def look_up_git_object(repo: dulwich.Repo,
        root_tree: Union[dulwich.objects.Tree, FileSystemFakeRepoTree],
        full_name: str, _max_symlink_depth: int | None = None):
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

    from dulwich.objects import Tree
    from course.validation import FileSystemFakeRepoTree

    cur_lookup = root_tree

    from stat import S_ISLNK
    while name_parts:
        if not isinstance(cur_lookup, (Tree, FileSystemFakeRepoTree)):
            raise ObjectDoesNotExist(
                    _("'%s' is not a directory, cannot lookup nested names")
                    % os.sep.join(processed_name_parts))

        name_part = name_parts.pop(0)

        if not name_part:
            # tolerate empty path components (begrudgingly)
            continue
        elif name_part == ".":
            return cur_lookup

        encoded_name_part = name_part.encode()
        try:
            mode_sha = cur_lookup[encoded_name_part]
        except KeyError:
            raise ObjectDoesNotExist(_("resource '%s' not found") % full_name)

        mode, cur_lookup_sha = mode_sha

        if S_ISLNK(mode):
            link_target = os.sep.join(processed_name_parts + [
                repo[cur_lookup_sha].data.decode()])
            cur_lookup = look_up_git_object(repo, root_tree, link_target,
                    _max_symlink_depth=_max_symlink_depth-1)
        else:
            processed_name_parts.append(name_part)
            cur_lookup = repo[cur_lookup_sha]

    return cur_lookup


def get_repo_blob(repo: Repo_ish, full_name: str, commit_sha: bytes,
        allow_tree: bool = True) -> dulwich.Blob:
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    :arg allow_tree: Allow the resulting object to be a directory
    """

    dul_repo, full_name = get_true_repo_and_path(repo, full_name)

    try:
        tree_sha = dul_repo[commit_sha].tree
    except KeyError:
        raise ObjectDoesNotExist(
                _("commit sha '%s' not found") % commit_sha.decode())

    git_obj = look_up_git_object(
            dul_repo, root_tree=dul_repo[tree_sha], full_name=full_name)

    from course.validation import FileSystemFakeRepoTree, FileSystemFakeRepoFile
    from dulwich.objects import Tree, Blob

    msg_full_name = full_name if full_name else _("(repo root)")

    if isinstance(git_obj, (Tree, FileSystemFakeRepoTree)):
        if allow_tree:
            return git_obj
        else:
            raise ObjectDoesNotExist(
                    _("resource '%s' is a directory, not a file") % msg_full_name)

    if isinstance(git_obj, (Blob, FileSystemFakeRepoFile)):
        return git_obj
    else:
        raise ObjectDoesNotExist(_("resource '%s' is not a file") % msg_full_name)


def get_repo_blob_data_cached(
        repo: Repo_ish, full_name: str, commit_sha: bytes) -> bytes:
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(commit_sha, bytes):
        from urllib.parse import quote_plus
        cache_key: str | None = "%s%R%1".join((
            CACHE_KEY_ROOT,
            quote_plus(repo.controldir()),
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
        result = get_repo_blob(repo, full_name, commit_sha,
                allow_tree=False).data
        assert isinstance(result, bytes)
        return result

    # Byte string is wrapped in a tuple to force pickling because memcache's
    # python wrapper appears to auto-decode/encode string values, thus trying
    # to decode our byte strings. Grr.

    def_cache = cache.caches["default"]

    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        cached_result = def_cache.get(cache_key)

        if cached_result is not None:
            (result,) = cached_result
            assert isinstance(result, bytes), cache_key
            return result

    result = get_repo_blob(repo, full_name, commit_sha,
            allow_tree=False).data
    assert result is not None

    if len(result) <= getattr(settings, "RELATE_CACHE_MAX_BYTES", 0):
        def_cache.add(cache_key, (result,), None)

    assert isinstance(result, bytes)

    return result


def is_repo_file_accessible_as(
        access_kinds: list[str], repo: Repo_ish, commit_sha: bytes, path: str
        ) -> bool:
    """
    Check of a file in a repo directory is accessible.  For example,
    'instructor' can access anything listed in the attributes.
    'student' can access 'student' and 'unenrolled'.  The 'unenrolled' role
    can only access 'unenrolled'.

    :arg commit_sha: A byte string containing the commit hash
    """

    # set the path to .attributes.yml
    attributes_path = os.path.join(os.path.dirname(path), ATTRIBUTES_FILENAME)

    # retrieve the .attributes.yml structure
    try:
        attributes = get_raw_yaml_from_repo(repo, attributes_path,
                                            commit_sha)
    except ObjectDoesNotExist:
        # no attributes file: not accessible
        return False

    path_basename = os.path.basename(path)

    # "public" is a deprecated alias for "unenrolled".

    access_patterns: list[str] = []
    for kind in access_kinds:
        access_patterns += attributes.get(kind, [])

    from fnmatch import fnmatch
    if isinstance(access_patterns, list):
        for pattern in access_patterns:
            if isinstance(pattern, str):
                if fnmatch(path_basename, pattern):
                    return True

    return False

# }}}


# {{{ jinja interaction

JINJA_YAML_RE = re.compile(
    r"^\[JINJA\]\s*$(.*?)^\[\/JINJA\]\s*$",
    re.MULTILINE | re.DOTALL)
YAML_BLOCK_START_SCALAR_RE = re.compile(
    r"(:\s*[|>])"
    "(J?)"
    "((?:[0-9][-+]?|[-+][0-9]?)?)"
    r"(?:\s*\#.*)?"
    "$")

IN_BLOCK_END_RAW_RE = re.compile(r"(.*)({%-?\s*endraw\s*-?%})(.*)")
GROUP_COMMENT_START = re.compile(r"^\s*#\s*\{\{\{")
LEADING_SPACES_RE = re.compile(r"^( *)")


def process_yaml_for_expansion(yaml_str: str) -> str:

    lines = yaml_str.split("\n")
    jinja_lines = []

    i = 0
    line_count = len(lines)

    while i < line_count:
        ln = lines[i].rstrip()
        yaml_block_scalar_match = YAML_BLOCK_START_SCALAR_RE.search(ln)

        if yaml_block_scalar_match is not None:
            unprocessed_block_lines = []
            allow_jinja = bool(yaml_block_scalar_match.group(2))
            ln = YAML_BLOCK_START_SCALAR_RE.sub(
                    r"\1\3", ln)

            unprocessed_block_lines.append(ln)

            leading_spaces_match = LEADING_SPACES_RE.match(ln)
            assert leading_spaces_match
            block_start_indent = len(leading_spaces_match.group(1))

            i += 1

            while i < line_count:
                ln = lines[i]

                if not ln.rstrip():
                    unprocessed_block_lines.append(ln)
                    i += 1
                    continue

                leading_spaces_match = LEADING_SPACES_RE.match(ln)
                assert leading_spaces_match
                line_indent = len(leading_spaces_match.group(1))
                if line_indent <= block_start_indent:
                    break
                else:
                    ln = IN_BLOCK_END_RAW_RE.sub(
                        r"\1{% endraw %}{{ '\2' }}{% raw %}\3", ln)
                    unprocessed_block_lines.append(ln.rstrip())
                    i += 1

            if not allow_jinja:
                jinja_lines.append("{% raw %}")
            jinja_lines.extend(unprocessed_block_lines)
            if not allow_jinja:
                jinja_lines.append("{% endraw %}")

        elif GROUP_COMMENT_START.match(ln):
            jinja_lines.append("{% raw %}")
            jinja_lines.append(ln)
            jinja_lines.append("{% endraw %}")
            i += 1

        else:
            jinja_lines.append(ln)
            i += 1
    return "\n".join(jinja_lines)


class GitTemplateLoader(BaseTemplateLoader):
    def __init__(self, repo: Repo_ish, commit_sha: bytes) -> None:
        self.repo = repo
        self.commit_sha = commit_sha

    def get_source(self, environment, template):
        try:
            data = get_repo_blob_data_cached(self.repo, template, self.commit_sha)
        except ObjectDoesNotExist:
            raise TemplateNotFound(template)

        source = data.decode("utf-8")

        def is_up_to_date():
            # There's not much point to caching here, because we create
            # a new loader for every request anyhow...
            return False

        return source, None, is_up_to_date


class YamlBlockEscapingGitTemplateLoader(GitTemplateLoader):
    # https://github.com/inducer/relate/issues/130

    def get_source(self, environment, template):
        source, path, is_up_to_date = \
                super().get_source(
                        environment, template)

        _, ext = os.path.splitext(template)
        ext = ext.lower()

        if ext in [".yml", ".yaml"]:
            source = process_yaml_for_expansion(source)

        return source, path, is_up_to_date


class YamlBlockEscapingFileSystemLoader(FileSystemLoader):
    # https://github.com/inducer/relate/issues/130

    def get_source(self, environment, template):
        source, path, is_up_to_date = \
                super().get_source(
                        environment, template)

        _, ext = os.path.splitext(template)
        ext = ext.lower()

        if ext in [".yml", ".yaml"]:
            source = process_yaml_for_expansion(source)

        return source, path, is_up_to_date


def expand_yaml_macros(repo: Repo_ish, commit_sha: bytes, yaml_str: str) -> str:

    if isinstance(yaml_str, bytes):
        yaml_str = yaml_str.decode("utf-8")

    from jinja2 import Environment, StrictUndefined
    jinja_env = Environment(
            loader=YamlBlockEscapingGitTemplateLoader(repo, commit_sha),
            undefined=StrictUndefined)

    # {{{ process explicit [JINJA] tags (deprecated)

    def compute_replacement(match):  # pragma: no cover  # deprecated
        template = jinja_env.from_string(match.group(1))
        return template.render()

    yaml_str, count = JINJA_YAML_RE.subn(compute_replacement, yaml_str)

    if count:  # pragma: no cover  # deprecated
        # The file uses explicit [JINJA] tags. Assume that it doesn't
        # want anything else processed through YAML.
        return yaml_str

    # }}}

    jinja_str = process_yaml_for_expansion(yaml_str)
    template = jinja_env.from_string(jinja_str)
    yaml_str = template.render()

    return yaml_str

# }}}


# {{{ repo yaml getting

def get_raw_yaml_from_repo(
        repo: Repo_ish, full_name: str, commit_sha: bytes) -> Any:
    """Return decoded YAML data structure from
    the given file in *repo* at *commit_sha*.

    :arg commit_sha: A byte string containing the commit hash
    """

    from urllib.parse import quote_plus
    cache_key = "%RAW%%2".join((
        CACHE_KEY_ROOT,
        quote_plus(repo.controldir()), quote_plus(full_name), commit_sha.decode(),
        ))

    import django.core.cache as cache
    def_cache = cache.caches["default"]

    result: Any | None = None
    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        result = def_cache.get(cache_key)
    if result is not None:
        return result

    yaml_str = expand_yaml_macros(
                repo, commit_sha,
                get_repo_blob(repo, full_name, commit_sha,
                    allow_tree=False).data)

    result = load_yaml(yaml_str)  # type: ignore

    def_cache.add(cache_key, result, None)

    return result


LINE_HAS_INDENTING_TABS_RE = re.compile(r"^\s*\t\s*", re.MULTILINE)


def get_yaml_from_repo(
        repo: Repo_ish, full_name: str, commit_sha: bytes, cached: bool = True,
        tolerate_tabs: bool = False) -> Any:
    """Return decoded, struct-ified YAML data structure from
    the given file in *repo* at *commit_sha*.

    See :class:`relate.utils.Struct` for more on
    struct-ification.

    :arg tolerate_tabs: At one point, Relate accepted tabs
        in indentation, but it no longer does. In places where legacy compatibility
        matters, you may set *tolerate_tabs* to *True*.
    """

    if cached:
        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            cached = False
        else:
            from urllib.parse import quote_plus
            cache_key = "%%%2".join(
                    (CACHE_KEY_ROOT,
                        quote_plus(repo.controldir()), quote_plus(full_name),
                        commit_sha.decode()))

            def_cache = cache.caches["default"]
            result = None
            # Memcache is apparently limited to 250 characters.
            if len(cache_key) < 240:
                result = def_cache.get(cache_key)
            if result is not None:
                return result

    yaml_bytestream = get_repo_blob(
            repo, full_name, commit_sha, allow_tree=False).data
    yaml_text = yaml_bytestream.decode("utf-8")

    if not tolerate_tabs and LINE_HAS_INDENTING_TABS_RE.search(yaml_text):
        raise ValueError("File uses tabs in indentation. "
                "This is not allowed.")

    expanded = expand_yaml_macros(
            repo, commit_sha, yaml_bytestream)

    yaml_data = load_yaml(expanded)  # type:ignore
    result = dict_to_struct(yaml_data)

    if cached:
        def_cache.add(cache_key, result, None)

    return result


# }}}


# {{{ markup

def _attr_to_string(key, val):
    if val is None:
        return key
    elif '"' in val:
        return f"{key}='{val}'"
    else:
        return f'{key}="{val}"'


class TagProcessingHTMLParser(html_parser.HTMLParser):
    def __init__(self, out_file, process_tag_func):
        html_parser.HTMLParser.__init__(self)

        self.out_file = out_file
        self.process_tag_func = process_tag_func

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<{} {}>".format(tag, " ".join(
            _attr_to_string(k, v) for k, v in attrs.items())))

    def handle_endtag(self, tag):
        self.out_file.write("</%s>" % tag)

    def handle_startendtag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<{} {}/>".format(tag, " ".join(
            _attr_to_string(k, v) for k, v in attrs.items())))

    def handle_data(self, data):
        self.out_file.write(data)

    def handle_entityref(self, name):
        self.out_file.write("&%s;" % name)

    def handle_charref(self, name):
        self.out_file.write("&#%s;" % name)

    def handle_comment(self, data):
        self.out_file.write("<!--%s-->" % data)

    def handle_decl(self, decl):
        self.out_file.write("<!%s>" % decl)

    def handle_pi(self, data):
        raise NotImplementedError(
                _("I have no idea what a processing instruction is."))

    def unknown_decl(self, data):
        self.out_file.write("<![%s]>" % data)


class PreserveFragment:
    def __init__(self, s):
        self.s = s


class LinkFixerTreeprocessor(Treeprocessor):
    def __init__(self, md, course, commit_sha, reverse_func):
        Treeprocessor.__init__(self)
        self.md = md
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def reverse(self, viewname, args):
        frag = None

        new_args = []
        for arg in args:
            if isinstance(arg, PreserveFragment):
                s = arg.s
                frag_index = s.find("#")
                if frag_index != -1:
                    frag = s[frag_index:]
                    s = s[:frag_index]

                new_args.append(s)
            else:
                new_args.append(arg)

        result = self.reverse_func(viewname, args=new_args)

        if frag is not None:
            result += frag

        return result

    def get_course_identifier(self):
        if self.course is None:
            return "bogus-course-identifier"
        else:
            return self.course.identifier

    def process_url(self, url):
        try:
            if url.startswith("course:"):
                course_id = url[7:]
                if course_id:
                    return self.reverse("relate-course_page",
                                args=(course_id,))
                else:
                    return self.reverse("relate-course_page",
                                args=(self.get_course_identifier(),))

            elif url.startswith("flow:"):
                flow_id = url[5:]
                return self.reverse("relate-view_start_flow",
                            args=(self.get_course_identifier(), flow_id))

            elif url.startswith("staticpage:"):
                page_path = url[11:]
                return self.reverse("relate-content_page",
                            args=(
                                self.get_course_identifier(),
                                PreserveFragment(page_path)))

            elif url.startswith("media:"):
                media_path = url[6:]
                return self.reverse("relate-get_media",
                            args=(
                                self.get_course_identifier(),
                                self.commit_sha.decode(),
                                PreserveFragment(media_path)))

            elif url.startswith("repo:"):
                path = url[5:]
                return self.reverse("relate-get_repo_file",
                            args=(
                                self.get_course_identifier(),
                                self.commit_sha.decode(),
                                PreserveFragment(path)))

            elif url.startswith("repocur:"):
                path = url[8:]
                return self.reverse("relate-get_current_repo_file",
                            args=(
                                self.get_course_identifier(),
                                PreserveFragment(path)))

            elif url.strip() == "calendar:":
                return self.reverse("relate-view_calendar",
                            args=(self.get_course_identifier(),))

            else:
                return None

        except NoReverseMatch:
            from base64 import b64encode
            message = ("Invalid character in RELATE URL: " + url).encode("utf-8")
            return "data:text/plain;base64,"+b64encode(message).decode()

    def process_tag(self, tag_name, attrs):
        changed_attrs = {}

        if tag_name == "table" and attrs.get("bootstrap") != "no":
            changed_attrs["class"] = "table table-condensed"

        if tag_name in ["a", "link"] and "href" in attrs:
            new_href = self.process_url(attrs["href"])

            if new_href is not None:
                changed_attrs["href"] = new_href

        elif tag_name == "img" and "src" in attrs:
            new_src = self.process_url(attrs["src"])

            if new_src is not None:
                changed_attrs["src"] = new_src

        elif tag_name == "object" and "data" in attrs:
            new_data = self.process_url(attrs["data"])

            if new_data is not None:
                changed_attrs["data"] = new_data

        return changed_attrs

    def process_etree_element(self, element):
        changed_attrs = self.process_tag(element.tag, element.attrib)

        for key, val in changed_attrs.items():
            element.set(key, val)

    def walk_and_process_tree(self, root):
        self.process_etree_element(root)

        for child in root:
            self.walk_and_process_tree(child)

    def run(self, root):
        self.walk_and_process_tree(root)

        # root through and process Markdown's HTML stash (gross!)
        from io import StringIO

        for i, (html, safe) in enumerate(self.md.htmlStash.rawHtmlBlocks):
            outf = StringIO()
            parser = TagProcessingHTMLParser(outf, self.process_tag)
            parser.feed(html)

            self.md.htmlStash.rawHtmlBlocks[i] = (outf.getvalue(), safe)


class LinkFixerExtension(Extension):
    def __init__(
            self, course: Course | None,
            commit_sha: bytes, reverse_func: Callable | None) -> None:
        Extension.__init__(self)
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def extendMarkdown(self, md, md_globals):  # noqa
        md.treeprocessors["relate_link_fixer"] = \
                LinkFixerTreeprocessor(md, self.course, self.commit_sha,
                        reverse_func=self.reverse_func)


def remove_prefix(prefix: str, s: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    else:
        return s


JINJA_PREFIX = "[JINJA]"


def expand_markup(
        course: Course | None,
        repo: Repo_ish,
        commit_sha: bytes,
        text: str,
        use_jinja: bool = True,
        jinja_env: dict = {},
        ) -> str:

    if not isinstance(text, str):
        text = str(text)

    # {{{ process through Jinja

    if use_jinja:
        from jinja2 import Environment, StrictUndefined
        env = Environment(
                loader=GitTemplateLoader(repo, commit_sha),
                undefined=StrictUndefined)

        template = env.from_string(text)
        kwargs = {}
        if jinja_env:
            kwargs.update(jinja_env)

        from course.utils import IpynbJinjaMacro
        kwargs[IpynbJinjaMacro.name] = IpynbJinjaMacro(course, repo, commit_sha)

        text = template.render(**kwargs)

    # }}}

    return text


def filter_html_attributes(tag, name, value):
    from bleach.sanitizer import ALLOWED_ATTRIBUTES

    allowed_attrs = ALLOWED_ATTRIBUTES.get(tag, [])
    result = name in allowed_attrs

    if tag == "a":
        result = (result
                or (name == "role" and value == "button")
                or (name == "class" and value.startswith("btn btn-")))
    elif tag == "img":
        result = result or name == "src"
    elif tag == "div":
        result = result or (name == "class" and value == "well")
    elif tag == "i":
        result = result or (name == "class" and value.startswith("fa fa-"))
    elif tag == "table":
        result = (result or (name == "class") or (name == "bootstrap"))

    return result


def markup_to_html(
        course: Course | None,
        repo: Repo_ish,
        commit_sha: bytes,
        text: str,
        reverse_func: Callable = None,
        validate_only: bool = False,
        use_jinja: bool = True,
        jinja_env: dict = {},
        ) -> str:

    disable_codehilite = bool(
        getattr(settings,
                "RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION", True))

    if course is not None and not jinja_env:
        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            cache_key = None
        else:
            import hashlib
            cache_key = ("markup:v8:%s:%d:%s:%s:%s%s"
                    % (CACHE_KEY_ROOT,
                       course.id, course.trusted_for_markup, str(commit_sha),
                       hashlib.md5(text.encode("utf-8")).hexdigest(),
                       ":NOCODEHILITE" if disable_codehilite else ""
                       ))

            def_cache = cache.caches["default"]
            result = def_cache.get(cache_key)
            if result is not None:
                assert isinstance(result, str)
                return result

        if text.lstrip().startswith(JINJA_PREFIX):
            text = remove_prefix(JINJA_PREFIX, text.lstrip())
    else:
        cache_key = None

    text = expand_markup(
            course, repo, commit_sha, text, use_jinja=use_jinja, jinja_env=jinja_env)

    if reverse_func is None:
        from django.urls import reverse
        reverse_func = reverse

    if validate_only:
        return ""

    from course.mdx_mathjax import MathJaxExtension
    from course.utils import NBConvertExtension
    import markdown

    extensions: list[markdown.Extension | str] = [
        LinkFixerExtension(course, commit_sha, reverse_func=reverse_func),
        MathJaxExtension(),
        NBConvertExtension(),
        "markdown.extensions.extra",
    ]

    if not disable_codehilite:
        # Note: no matter whether disable_codehilite, the code in
        # the rendered ipython notebook will be highlighted.
        # "css_class=highlight" is to ensure that, when codehilite extension
        # is enabled, code out side of notebook uses the same html class
        # attribute as the default highlight class (i.e., `highlight`)
        # used by rendered ipynb notebook cells, Thus we don't need to
        # make 2 copies of css for the highlight.
        extensions += ["markdown.extensions.codehilite(css_class=highlight)"]

    result = markdown.markdown(text,
        extensions=extensions,
        output_format="html")

    if course is None or not course.trusted_for_markup:
        import bleach
        result = bleach.clean(result,
                tags=bleach.ALLOWED_TAGS + [
                    "div", "span", "p", "img",
                    "h1", "h2", "h3", "h4", "h5", "h6",
                    "table", "td", "tr", "th",
                    ],
                attributes=filter_html_attributes)

    assert isinstance(result, str)
    if cache_key is not None:
        def_cache.add(cache_key, result, None)

    return result


TITLE_RE = re.compile(r"^\#+\s*(.+)", re.UNICODE)


def extract_title_from_markup(markup_text: str) -> str | None:
    lines = markup_text.split("\n")

    for ln in lines[:10]:
        match = TITLE_RE.match(ln)
        if match is not None:
            return match.group(1)

    return None

# }}}


# {{{ datespec processing

DATE_RE = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
TRAILING_NUMERAL_RE = re.compile(r"^(.*)\s+([0-9]+)$")

END_PREFIX = "end:"


class InvalidDatespec(ValueError):
    def __init__(self, datespec):
        ValueError.__init__(self, str(datespec))
        self.datespec = datespec


class DatespecPostprocessor:
    @classmethod
    def parse(cls, s: str) -> tuple[str, DatespecPostprocessor | None]:
        raise NotImplementedError()

    def apply(self, dtm: datetime.datetime) -> datetime.datetime:
        raise NotImplementedError()


AT_TIME_RE = re.compile(r"^(.*)\s*@\s*([0-2]?[0-9])\:([0-9][0-9])\s*$")


class AtTimePostprocessor(DatespecPostprocessor):
    def __init__(self, hour: int, minute: int, second: int = 0) -> None:
        self.hour = hour
        self.minute = minute
        self.second = second

    @classmethod
    def parse(cls, s):
        match = AT_TIME_RE.match(s)
        if match is not None:
            hour = int(match.group(2))
            minute = int(match.group(3))

            if not (0 <= hour < 24):
                raise InvalidDatespec(s)

            if not (0 <= minute < 60):
                raise InvalidDatespec(s)

            return match.group(1), AtTimePostprocessor(hour, minute)
        else:
            return s, None

    def apply(self, dtm):
        from pytz import timezone
        server_tz = timezone(settings.TIME_ZONE)

        return dtm.astimezone(server_tz).replace(
                    hour=self.hour,
                    minute=self.minute,
                    second=self.second)


PLUS_DELTA_RE = re.compile(r"^(.*)\s*([+-])\s*([0-9]+)\s+"
    "(weeks?|days?|hours?|minutes?)$")


class PlusDeltaPostprocessor(DatespecPostprocessor):
    def __init__(self, count: int, period: str) -> None:

        self.count = count
        self.period = period

    @classmethod
    def parse(cls, s):
        match = PLUS_DELTA_RE.match(s)
        if match is not None:
            count = int(match.group(3))
            if match.group(2) == "-":
                count = -count
            period = match.group(4)

            return match.group(1), PlusDeltaPostprocessor(count, period)
        else:
            return s, None

    def apply(self, dtm):
        if self.period.startswith("week"):
            d = datetime.timedelta(weeks=self.count)
        elif self.period.startswith("day"):
            d = datetime.timedelta(days=self.count)
        elif self.period.startswith("hour"):
            d = datetime.timedelta(hours=self.count)
        else:
            assert self.period.startswith("minute")
            d = datetime.timedelta(minutes=self.count)
        return dtm + d


DATESPEC_POSTPROCESSORS: list[Any] = [
        AtTimePostprocessor,
        PlusDeltaPostprocessor,
        ]


def parse_date_spec(
        course: Course | None,
        datespec: str | datetime.date | datetime.datetime,
        vctx: ValidationContext | None = None,
        location: str | None = None,
        ) -> datetime.datetime:

    if datespec is None:
        return None

    orig_datespec = datespec

    def localize_if_needed(d: datetime.datetime) -> datetime.datetime:
        if d.tzinfo is None:
            from relate.utils import localize_datetime
            return localize_datetime(d)
        else:
            return d

    if isinstance(datespec, datetime.datetime):
        return localize_if_needed(datespec)
    if isinstance(datespec, datetime.date):
        return localize_if_needed(
                datetime.datetime.combine(datespec, datetime.time.min))

    datespec_str = cast(str, datespec).strip()

    # {{{ parse postprocessors

    postprocs: list[DatespecPostprocessor] = []
    while True:
        parsed_one = False
        for pp_class in DATESPEC_POSTPROCESSORS:
            datespec_str, postproc = pp_class.parse(datespec_str)
            if postproc is not None:
                parsed_one = True
                postprocs.insert(0, cast(DatespecPostprocessor, postproc))
                break

        datespec_str = datespec_str.strip()

        if not parsed_one:
            break

    # }}}

    def apply_postprocs(dtime: datetime.datetime) -> datetime.datetime:
        for postproc in postprocs:
            dtime = postproc.apply(dtime)

        return dtime

    match = DATE_RE.match(datespec_str)
    if match:
        res_date = datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)))
        result = localize_if_needed(
                datetime.datetime.combine(res_date, datetime.time.min))
        return apply_postprocs(result)

    is_end = datespec_str.startswith(END_PREFIX)
    if is_end:
        datespec_str = datespec_str[len(END_PREFIX):]

    match = TRAILING_NUMERAL_RE.match(datespec_str)
    if match:
        # event with numeral

        event_kind = match.group(1)
        ordinal: int | None = int(match.group(2))

    else:
        # event without numeral

        event_kind = datespec_str
        ordinal = None

    if vctx is not None:
        from course.validation import validate_identifier
        validate_identifier(vctx, "%s: event kind" % location, event_kind)

    if course is None:
        return now()

    from course.models import Event

    try:
        event_obj = Event.objects.get(
            course=course,
            kind=event_kind,
            ordinal=ordinal)

    except ObjectDoesNotExist:
        if vctx is not None:
            vctx.add_warning(
                    location,
                    _("Unrecognized date/time specification: '%s' "
                    "(interpreted as 'now'). "
                    "You should add an event with this name.")
                    % orig_datespec)
        return now()

    if is_end:
        if event_obj.end_time is not None:
            result = event_obj.end_time
        else:
            result = event_obj.time
            if vctx is not None:
                vctx.add_warning(
                        location,
                        _("event '%s' has no end time, using start time instead")
                        % orig_datespec)

    else:
        result = event_obj.time

    return apply_postprocs(result)


# }}}


# {{{ page chunks

def compute_chunk_weight_and_shown(
        course: Course,
        chunk: ChunkDesc,
        roles: list[str],
        now_datetime: datetime.datetime,
        facilities: frozenset[str],
        ) -> tuple[float, bool]:
    if not hasattr(chunk, "rules"):
        return 0, True

    for rule in chunk.rules:
        if hasattr(rule, "if_has_role"):
            if all(role not in rule.if_has_role for role in roles):
                continue

        if hasattr(rule, "if_after"):
            start_date = parse_date_spec(course, rule.if_after)
            if now_datetime < start_date:
                continue

        if hasattr(rule, "if_before"):
            end_date = parse_date_spec(course, rule.if_before)
            if end_date < now_datetime:
                continue

        if hasattr(rule, "if_in_facility"):
            if rule.if_in_facility not in facilities:
                continue

        # {{{ deprecated

        if hasattr(rule, "roles"):  # pragma: no cover  # deprecated
            if all(role not in rule.roles for role in roles):
                continue

        if hasattr(rule, "start"):  # pragma: no cover  # deprecated
            start_date = parse_date_spec(course, rule.start)
            if now_datetime < start_date:
                continue

        if hasattr(rule, "end"):  # pragma: no cover  # deprecated
            end_date = parse_date_spec(course, rule.end)
            if end_date < now_datetime:
                continue

        # }}}

        shown = True
        if hasattr(rule, "shown"):
            shown = rule.shown

        return rule.weight, shown

    return 0, True


def get_processed_page_chunks(
        course: Course,
        repo: Repo_ish,
        commit_sha: bytes,
        page_desc: StaticPageDesc,
        roles: list[str],
        now_datetime: datetime.datetime,
        facilities: frozenset[str],
        ) -> list[ChunkDesc]:
    for chunk in page_desc.chunks:
        chunk.weight, chunk.shown = \
                compute_chunk_weight_and_shown(
                        course, chunk, roles, now_datetime,
                        facilities)
        chunk.html_content = markup_to_html(course, repo, commit_sha, chunk.content)
        if not hasattr(chunk, "title"):
            chunk.title = extract_title_from_markup(chunk.content)

    page_desc.chunks.sort(key=lambda chunk: chunk.weight, reverse=True)

    return [chunk for chunk in page_desc.chunks
            if chunk.shown]


# }}}


# {{{ repo desc getting

def normalize_page_desc(page_desc: StaticPageDesc) -> StaticPageDesc:
    if hasattr(page_desc, "content"):
        content = page_desc.content
        from relate.utils import struct_to_dict, Struct
        d = struct_to_dict(page_desc)
        del d["content"]
        d["chunks"] = [Struct({"id": "main", "content": content})]
        return cast(StaticPageDesc, Struct(d))

    return page_desc


def get_staticpage_desc(
        repo: Repo_ish, course: Course, commit_sha: bytes, filename: str
        ) -> StaticPageDesc:

    page_desc = get_yaml_from_repo(repo, filename, commit_sha)
    page_desc = normalize_page_desc(page_desc)
    return page_desc


def get_course_desc(repo: Repo_ish, course: Course, commit_sha: bytes) -> CourseDesc:

    return cast(
            CourseDesc,
            get_staticpage_desc(repo, course, commit_sha, course.course_file))


def normalize_flow_desc(flow_desc: FlowDesc) -> FlowDesc:

    if hasattr(flow_desc, "pages"):
        pages = flow_desc.pages
        from relate.utils import struct_to_dict, Struct
        d = struct_to_dict(flow_desc)
        del d["pages"]
        d["groups"] = [Struct({"id": "main", "pages": pages})]
        return cast(FlowDesc, Struct(d))

    if hasattr(flow_desc, "rules"):
        rules = flow_desc.rules
        if not hasattr(rules, "grade_identifier"):  # pragma: no cover  # deprecated
            # Legacy content with grade_identifier in grading rule,
            # move first found grade_identifier up to rules.

            rules.grade_identifier = None
            rules.grade_aggregation_strategy = None

            for grule in rules.grading:
                if grule.grade_identifier is not None:  # type: ignore
                    rules.grade_identifier = grule.grade_identifier  # type: ignore
                    rules.grade_aggregation_strategy = (  # type: ignore
                            grule.grade_aggregation_strategy)  # type: ignore
                    break

    return flow_desc


def get_flow_desc(
        repo: Repo_ish, course: Course, flow_id: str,
        commit_sha: bytes, tolerate_tabs: bool = False) -> FlowDesc:
    """
    :arg tolerate_tabs: At one point, Relate accepted tabs
        in indentation, but it no longer does. In places where legacy
        compatibility matters, you may set *tolerate_tabs* to *True*.
    """

    # FIXME: extension should be case-insensitive
    flow_desc = get_yaml_from_repo(repo, "flows/%s.yml" % flow_id, commit_sha,
            tolerate_tabs=tolerate_tabs)

    flow_desc = normalize_flow_desc(flow_desc)

    flow_desc.description_html = markup_to_html(
            course, repo, commit_sha, getattr(flow_desc, "description", None))
    return flow_desc


def get_flow_page_desc(flow_id: str, flow_desc: FlowDesc,
        group_id: str, page_id: str) -> FlowPageDesc:
    for grp in flow_desc.groups:
        if grp.id == group_id:
            for page in grp.pages:
                if page.id == page_id:
                    return page

    raise ObjectDoesNotExist(
            _("page '%(group_id)s/%(page_id)s' in flow '%(flow_id)s'") % {
                "group_id": group_id,
                "page_id": page_id,
                "flow_id": flow_id
                })

# }}}


# {{{ flow page handling

class ClassNotFoundError(RuntimeError):
    pass


def import_class(name: str) -> type:
    components = name.split(".")

    if len(components) < 2:
        # need at least one module plus class name
        raise ClassNotFoundError(name)

    module_name = ".".join(components[:-1])
    try:
        mod = __import__(module_name)
    except ImportError:
        raise ClassNotFoundError(name)

    for comp in components[1:]:
        try:
            mod = getattr(mod, comp)
        except AttributeError:
            raise ClassNotFoundError(name)

    return mod


def get_flow_page_class(repo: Repo_ish, typename: str, commit_sha: bytes) -> type:

    # look among default page types
    import course.page
    try:
        return getattr(course.page, typename)
    except AttributeError:
        pass

    # try a global dotted-name import
    try:
        return import_class(typename)
    except ClassNotFoundError:
        pass

    raise ClassNotFoundError(typename)


def instantiate_flow_page(
        location: str, repo: Repo_ish, page_desc: FlowPageDesc, commit_sha: bytes
        ) -> PageBase:
    class_ = get_flow_page_class(repo, page_desc.type, commit_sha)

    return class_(None, location, page_desc)

# }}}


class CourseCommitSHADoesNotExist(Exception):
    pass


def get_course_commit_sha(
        course: Course,
        participation: Participation | None,
        repo: Repo_ish | None = None,
        raise_on_nonexistent_preview_commit: bool | None = False
        ) -> bytes:
    sha = course.active_git_commit_sha

    def is_commit_sha_valid(repo: Repo_ish, commit_sha: str) -> bool:
        if isinstance(repo, SubdirRepoWrapper):
            repo = repo.repo
        try:
            repo[commit_sha.encode()]
        except KeyError:
            if raise_on_nonexistent_preview_commit:
                raise CourseCommitSHADoesNotExist(
                    _("Preview revision '%s' does not exist--"
                      "showing active course content instead."
                      % commit_sha))
            return False

        return True

    if participation is not None:
        if participation.preview_git_commit_sha:
            preview_sha = participation.preview_git_commit_sha

            if repo is not None:
                commit_sha_valid = is_commit_sha_valid(repo, preview_sha)
            else:
                with get_course_repo(course) as repo:
                    commit_sha_valid = is_commit_sha_valid(repo, preview_sha)

            if not commit_sha_valid:
                preview_sha = None

            if preview_sha is not None:
                sha = preview_sha

    return sha.encode()


def list_flow_ids(repo: Repo_ish, commit_sha: bytes) -> list[str]:
    flow_ids = []
    try:
        flows_tree = get_repo_blob(repo, "flows", commit_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in flows_tree.items():
            if entry.path.endswith(b".yml"):
                flow_ids.append(entry.path[:-4].decode("utf-8"))

    return sorted(flow_ids)

# vim: foldmethod=marker
