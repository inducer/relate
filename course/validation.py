# -*- coding: utf-8 -*-

from __future__ import division, print_function

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

import re
import datetime
import sys

from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import escape
from django.utils.translation import (
        gettext_lazy as _, gettext)
from course.constants import (
        FLOW_SESSION_EXPIRATION_MODE_CHOICES,
        ATTRIBUTES_FILENAME, DEFAULT_ACCESS_KINDS,
        participation_permission as pperm)

from course.content import get_repo_blob
from relate.utils import Struct, string_concat

# {{{ mypy

from typing import Any, Tuple, Optional, Text, List, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from relate.utils import Repo_ish  # noqa
    from course.models import Course  # noqa

# }}}


__doc__ = """
.. autoclass:: ValidationContext

.. autofunction:: validate_struct

Stub Docs
=========

.. class:: Course
.. class:: Repo_ish
"""


# {{{ validation tools

class ValidationError(RuntimeError):
    pass


ID_RE = re.compile(r"^[\w]+$")


def validate_identifier(vctx, location, s, warning_only=False):
    # type: (ValidationContext, Text, Text, bool) -> None

    if not ID_RE.match(s):

        if warning_only:
            msg = (string_concat(
                        _("invalid identifier"),
                        " '%(string)s'")
                    % {'location': location, 'string': s})

            vctx.add_warning(location, msg)
        else:
            msg = (string_concat(
                        "%(location)s: ",
                        _("invalid identifier"),
                        " '%(string)s'")
                    % {'location': location, 'string': s})

            raise ValidationError(msg)


def validate_role(vctx, location, role):
    # type: (ValidationContext, Text, Text) -> None

    if vctx.course is not None:
        from course.models import ParticipationRole
        roles = ParticipationRole.objects.filter(course=vctx.course).values_list(
                "identifier", flat=True)

        if role not in roles:
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("invalid role '%(role)s'"))
                    % {'location': location, 'role': role})


def validate_facility(vctx, location, facility):
    # type: (ValidationContext, Text, Text) -> None

    from course.utils import get_facilities_config
    facilities = get_facilities_config()
    if facilities is None:
        return

    if facility not in facilities:
        vctx.add_warning(location, _(
            "Name of facility not recognized: '%(fac_name)s'. "
            "Known facility names: '%(known_fac_names)s'")
            % {
                "fac_name": facility,
                "known_fac_names": ", ".join(facilities),
                })


def validate_participationtag(vctx, location, participationtag):
    # type: (ValidationContext, Text, Text) -> None

    if vctx.course is not None:
        from pytools import memoize_in

        @memoize_in(vctx, "available_participation_tags")
        def get_ptag_list(vctx):
            # type: (ValidationContext) -> List[str]
            from course.models import ParticipationTag
            return list(
                ParticipationTag.objects.filter(course=vctx.course)
                .values_list('name', flat=True))

        ptag_list = get_ptag_list(vctx)
        if participationtag not in ptag_list:
            vctx.add_warning(
                location,
                _(
                    "Name of participation tag not recognized: '%(ptag_name)s'. "
                    "Known participation tag names: '%(known_ptag_names)s'")
                % {
                    "ptag_name": participationtag,
                    "known_ptag_names": ", ".join(ptag_list),
                })


def validate_struct(
        vctx,  # type: ValidationContext
        location,  # type: Text
        obj,  # type: Any
        required_attrs,  # type: List[Tuple[Text, Any]]
        allowed_attrs,  # type: List[Tuple[Text, Any]]
        ):
    # type: (...) -> None

    """
    :arg required_attrs: an attribute validation list (see below)
    :arg allowed_attrs: an attribute validation list (see below)

    An attribute validation list is a list of elements, where each element is
    either a string (the name of the attribute), in which case the type of each
    attribute is not checked, or a tuple *(name, type)*, where type is valid
    as a second argument to :func:`isinstance`.
    """

    if not isinstance(obj, Struct):
        raise ValidationError(
                "%s: not a key-value map" % location)

    present_attrs = set(name for name in dir(obj) if not name.startswith("_"))

    for required, attr_list in [
            (True, required_attrs),
            (False, allowed_attrs),
            ]:
        for attr_rec in attr_list:
            if isinstance(attr_rec, tuple):
                attr, allowed_types = attr_rec
            else:
                attr = attr_rec
                allowed_types = None

            if attr not in present_attrs:
                if required:
                    raise ValidationError(
                            string_concat("%(location)s: ",
                                _("attribute '%(attr)s' missing"))
                            % {'location': location, 'attr': attr})
            else:
                present_attrs.remove(attr)
                val = getattr(obj, attr)

                is_markup = False
                if allowed_types == "markup":
                    allowed_types = str
                    is_markup = True

                if not isinstance(val, allowed_types):
                    raise ValidationError(
                            string_concat("%(location)s: ",
                                _("attribute '%(attr)s' has "
                                    "wrong type: got '%(name)s', "
                                    "expected '%(allowed)s'"))
                            % {
                                'location': location,
                                'attr': attr,
                                'name': type(val).__name__,
                                'allowed': escape(str(allowed_types))})

                if is_markup:
                    validate_markup(vctx, "%s: attribute %s" % (location, attr), val)

    if present_attrs:
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("extraneous attribute(s) '%(attr)s'"))
                % {'location': location, 'attr': ",".join(present_attrs)})


datespec_types = (datetime.date, str, datetime.datetime)

# }}}


class ValidationWarning(object):
    def __init__(self, location, text):
        # type: (Optional[Text], Text) -> None
        self.location = location
        self.text = text


class ValidationContext(object):
    """
    .. attribute:: repo
    .. attribute:: commit_sha
    .. attribute:: course

        A :class:`course.models.Course` instance, or *None*, if no database
        is currently available.
    """

    course = None  # type: Optional[Course]

    def __init__(self, repo, commit_sha, course=None):
        # type: (Repo_ish, bytes, Optional[Course]) -> None

        self.repo = repo
        self.commit_sha = commit_sha
        self.course = course

        self.warnings = []  # type: List[ValidationWarning]

    def encounter_datespec(self, location, datespec):
        # type: (Text, Text) -> None

        from course.content import parse_date_spec
        parse_date_spec(self.course, datespec, vctx=self, location=location)

    def add_warning(self, location, text):
        # type: (Optional[Text], Text) -> None
        self.warnings.append(ValidationWarning(location, text))


# {{{ markup validation

def validate_markup(vctx, location, markup_str):
    # type: (ValidationContext, Text, Text) -> None

    def reverse_func(*args, **kwargs):
        pass

    from course.content import markup_to_html
    try:
        markup_to_html(
                course=None,
                repo=vctx.repo,
                commit_sha=vctx.commit_sha,
                text=markup_str,
                reverse_func=reverse_func,
                validate_only=True)
    except Exception:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        assert tp is not None

        raise ValidationError(
                "%(location)s: %(err_type)s: %(err_str)s" % {
                    'location': location,
                    "err_type": tp.__name__,
                    "err_str": str(e)})

# }}}


# {{{ course page validation

def validate_chunk_rule(vctx, location, chunk_rule):
    validate_struct(
            vctx,
            location,
            chunk_rule,
            required_attrs=[
                ("weight", int),
                ],
            allowed_attrs=[
                ("if_after", datespec_types),
                ("if_before", datespec_types),
                ("if_in_facility", str),
                ("if_has_role", list),
                ("if_has_participation_tags_any", list),
                ("if_has_participation_tags_all", list),

                ("start", datespec_types),
                ("end", datespec_types),
                ("roles", list),

                ("shown", bool),
            ])

    if hasattr(chunk_rule, "if_after"):
        vctx.encounter_datespec(location, chunk_rule.if_after)

    if hasattr(chunk_rule, "if_before"):
        vctx.encounter_datespec(location, chunk_rule.if_before)

    if hasattr(chunk_rule, "if_has_role"):
        for role in chunk_rule.if_has_role:
            validate_role(vctx, location, role)

    if hasattr(chunk_rule, "if_has_participation_tags_any"):
        for ptag in chunk_rule.if_has_participation_tags_any:
            validate_participationtag(vctx, location, ptag)

    if hasattr(chunk_rule, "if_has_participation_tags_all"):
        for ptag in chunk_rule.if_has_participation_tags_all:
            validate_participationtag(vctx, location, ptag)

    if hasattr(chunk_rule, "if_in_facility"):
        validate_facility(vctx, location, chunk_rule.if_in_facility)

    # {{{ deprecated

    if hasattr(chunk_rule, "start"):
        vctx.add_warning(location, _("Uses deprecated 'start' attribute--"
                "use 'if_after' instead"))

        vctx.encounter_datespec(location, chunk_rule.start)

    if hasattr(chunk_rule, "end"):
        vctx.add_warning(location, _("Uses deprecated 'end' attribute--"
                "use 'if_before' instead"))

        vctx.encounter_datespec(location, chunk_rule.end)

    if hasattr(chunk_rule, "roles"):
        vctx.add_warning(location, _("Uses deprecated 'roles' attribute--"
                "use 'if_has_role' instead"))

        for role in chunk_rule.roles:
            validate_role(vctx, location, role)

    # }}}


def validate_page_chunk(vctx, location, chunk):
    validate_struct(
            vctx,
            location,
            chunk,
            required_attrs=[
                ("id", str),
                ("content", "markup"),
                ],
            allowed_attrs=[
                ("title", str),
                ("rules", list),
                ]
            )

    title = getattr(chunk, "title", None)
    if title is None:
        from course.content import extract_title_from_markup
        title = extract_title_from_markup(chunk.content)

    if title is None:
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("no title present"))
                % {'location': location})

    if hasattr(chunk, "rules"):
        for i, rule in enumerate(chunk.rules):
            validate_chunk_rule(vctx,
                    "%s, rule %d" % (location, i+1),
                    rule)

    validate_markup(vctx, location, chunk.content)


def validate_staticpage_desc(vctx, location, page_desc):
    validate_struct(
            vctx,
            location,
            page_desc,
            required_attrs=[
                ],
            allowed_attrs=[
                ("chunks", list),
                ("content", str),
                ]
            )

    # {{{ check for presence of 'chunks' or 'content'

    if (
            (not hasattr(page_desc, "chunks") and not hasattr(page_desc, "content"))
            or (hasattr(page_desc, "chunks") and hasattr(page_desc, "content"))):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("must have either 'chunks' or 'content'"))
                % {'location': location})

    # }}}

    if hasattr(page_desc, "content"):
        from course.content import normalize_page_desc
        page_desc = normalize_page_desc(page_desc)

        assert not hasattr(page_desc, "content")
        assert hasattr(page_desc, "chunks")

    for i, chunk in enumerate(page_desc.chunks):
        validate_page_chunk(vctx,
                "%s, chunk %d ('%s')"
                % (location, i+1, getattr(chunk, "id", None)),
                chunk)

    # {{{ check chunk id uniqueness

    chunk_ids = set()

    for chunk in page_desc.chunks:
        if chunk.id in chunk_ids:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("chunk id '%(chunkid)s' not unique"))
                    % {'location': location, 'chunkid': chunk.id})

        chunk_ids.add(chunk.id)

    # }}}

# }}}


# {{{ flow validation

def validate_flow_page(vctx, location, page_desc):
    # type: (ValidationContext, Text, Any) -> None
    if not hasattr(page_desc, "id"):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    gettext("flow page has no ID"))
                % location)

    validate_identifier(vctx, location, page_desc.id)

    if page_desc.type.startswith("repo:"):
        from django.conf import settings
        from course.utils import get_custom_page_types_stop_support_deadline
        from relate.utils import local_now, format_datetime_local

        deadline = get_custom_page_types_stop_support_deadline()

        assert deadline is not None

        if deadline < local_now():
            raise ValidationError(
                    location,
                    _("Custom page type '%(page_type)s' specified. "
                      "Custom page types were no longer supported in "
                      "%(relate_site_name)s since %(date_time)s.")
                    % {"page_type": page_desc.type,
                       "date_time": format_datetime_local(deadline),
                       "relate_site_name": settings.RELATE_SITE_NAME,
                       })
        else:
            vctx.add_warning(
                    location,
                    _("Custom page type '%(page_type)s' specified. "
                      "Custom page types will stop being supported in "
                      "%(relate_site_name)s at %(date_time)s.")
                    % {"page_type": page_desc.type,
                       "date_time": format_datetime_local(deadline),
                       "relate_site_name": settings.RELATE_SITE_NAME
                       })

    from course.content import get_flow_page_class
    try:
        class_ = get_flow_page_class(vctx.repo, page_desc.type, vctx.commit_sha)
        class_(vctx, location, page_desc)
    except ValidationError:
        raise
    except Exception:
        tp, e, __ = sys.exc_info()

        from traceback import format_exc
        raise ValidationError(
                string_concat(
                    "%(location)s: ",
                    _("could not instantiate flow page"),
                    ": %(err_type)s: "
                    "%(err_str)s<br><pre>%(format_exc)s</pre>")
                % {
                    'location': location,
                    "err_type": tp.__name__,  # type: ignore
                    "err_str": str(e),
                    'format_exc': format_exc()})


def validate_flow_group(vctx, location, grp):
    validate_struct(
            vctx,
            location,
            grp,
            required_attrs=[
                ("id", str),
                ("pages", list),
                ],
            allowed_attrs=[
                ("shuffle", bool),
                ("max_page_count", int),
                ]
            )

    if len(grp.pages) == 0:
        raise ValidationError(
                string_concat(
                    "%(location)s, ",
                    _("group '%(group_id)s': group is empty"))
                % {'location': location, 'group_id': grp.id})

    for i, page_desc in enumerate(grp.pages):
        validate_flow_page(
                vctx,
                "%s, page %d ('%s')"
                % (location, i+1, getattr(page_desc, "id", None)),
                page_desc)

    if hasattr(grp, "max_page_count"):
        if grp.max_page_count <= 0:
            raise ValidationError(
                string_concat(
                    "%(location)s, ",
                    _("group '%(group_id)s': "
                        "max_page_count is not positive"))
                % {'location': location, 'group_id': grp.id})
        elif not hasattr(grp, "shuffle") and grp.max_page_count < len(grp.pages):
            vctx.add_warning(
                _("%(location)s, group '%(group_id)s': ") % {
                    'location': location, 'group_id': grp.id},
                _("shuffle attribute will be required for groups with"
                  "max_page_count in a future version. set "
                  "'shuffle: False' to match current behavior."))

    # {{{ check page id uniqueness

    page_ids = set()

    for page_desc in grp.pages:
        if page_desc.id in page_ids:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("page id '%(page_desc_id)s' not unique"))
                    % {'location': location, 'page_desc_id': page_desc.id})

        page_ids.add(page_desc.id)

    # }}}

    validate_identifier(vctx, location, grp.id)


# {{{ flow rules

def validate_session_start_rule(vctx, location, nrule, tags):
    # type: (ValidationContext, Text, Any, List[Text]) -> None
    validate_struct(
            vctx, location, nrule,
            required_attrs=[],
            allowed_attrs=[
                ("if_after", datespec_types),
                ("if_before", datespec_types),
                ("if_has_role", list),
                ("if_has_participation_tags_any", list),
                ("if_has_participation_tags_all", list),
                ("if_in_facility", str),
                ("if_has_in_progress_session", bool),
                ("if_has_session_tagged", (str, type(None))),
                ("if_has_fewer_sessions_than", int),
                ("if_has_fewer_tagged_sessions_than", int),
                ("if_signed_in_with_matching_exam_ticket", bool),
                ("tag_session", (str, type(None))),
                ("may_start_new_session", bool),
                ("may_list_existing_sessions", bool),
                ("lock_down_as_exam_session", bool),
                ("default_expiration_mode", str),
                ]
            )

    if hasattr(nrule, "if_after"):
        vctx.encounter_datespec(location, nrule.if_after)
    if hasattr(nrule, "if_before"):
        vctx.encounter_datespec(location, nrule.if_before)
    if hasattr(nrule, "if_has_role"):
        for j, role in enumerate(nrule.if_has_role):
            validate_role(
                    vctx,
                    "%s, role %d" % (location, j+1),
                    role)

    if hasattr(nrule, "if_has_participation_tags_any"):
        for ptag in nrule.if_has_participation_tags_any:
            validate_participationtag(vctx, location, ptag)

    if hasattr(nrule, "if_has_participation_tags_all"):
        for ptag in nrule.if_has_participation_tags_all:
            validate_participationtag(vctx, location, ptag)

    if hasattr(nrule, "if_in_facility"):
        validate_facility(vctx, location, nrule.if_in_facility)

    if hasattr(nrule, "if_has_session_tagged"):
        if nrule.if_has_session_tagged is not None:
            validate_identifier(vctx, "%s: if_has_session_tagged" % location,
                    nrule.if_has_session_tagged)

    if not hasattr(nrule, "may_start_new_session"):
        vctx.add_warning(
                location+", rules",
                _("attribute 'may_start_new_session' is not present"))
    if not hasattr(nrule, "may_list_existing_sessions"):
        vctx.add_warning(
                location+", rules",
                _("attribute 'may_list_existing_sessions' is not present"))
    if hasattr(nrule, "lock_down_as_exam_session"):
        vctx.add_warning(
                location+", rules",
                _("Attribute 'lock_down_as_exam_session' is deprecated "
                "and non-functional. Use the access permission flag "
                "'lock_down_as_exam_session' instead."))

    if hasattr(nrule, "tag_session"):
        if nrule.tag_session is not None:
            validate_identifier(vctx, "%s: tag_session" % location,
                    nrule.tag_session,
                    warning_only=True)

        if not (nrule.tag_session is None or nrule.tag_session in tags):
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': nrule.tag_session})

    if hasattr(nrule, "default_expiration_mode"):
        from course.constants import FLOW_SESSION_EXPIRATION_MODE_CHOICES
        if nrule.default_expiration_mode not in dict(
                FLOW_SESSION_EXPIRATION_MODE_CHOICES):
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("invalid default expiration mode '%(expiremode)s'"))
                    % {
                        'location': location,
                        'expiremode': nrule.default_expiration_mode})


def validate_session_access_rule(vctx, location, arule, tags):
    # type: (ValidationContext, Text, Any, List[Text]) -> None
    validate_struct(
            vctx, location, arule,
            required_attrs=[
                ("permissions", list),
                ],
            allowed_attrs=[
                ("if_after", datespec_types),
                ("if_before", datespec_types),
                ("if_started_before", datespec_types),
                ("if_has_role", list),
                ("if_has_participation_tags_any", list),
                ("if_has_participation_tags_all", list),
                ("if_in_facility", str),
                ("if_has_tag", (str, type(None))),
                ("if_in_progress", bool),
                ("if_completed_before", datespec_types),
                ("if_expiration_mode", str),
                ("if_session_duration_shorter_than_minutes", (int, float)),
                ("if_signed_in_with_matching_exam_ticket", bool),
                ("message", str),
                ]
            )

    if hasattr(arule, "if_after"):
        vctx.encounter_datespec(location, arule.if_after)
    if hasattr(arule, "if_before"):
        vctx.encounter_datespec(location, arule.if_before)
    if hasattr(arule, "if_completed_before"):
        vctx.encounter_datespec(location, arule.if_completed_before)

    if hasattr(arule, "if_has_role"):
        for j, role in enumerate(arule.if_has_role):
            validate_role(
                    vctx,
                    "%s, role %d" % (location, j+1),
                    role)

    if hasattr(arule, "if_has_participation_tags_any"):
        for ptag in arule.if_has_participation_tags_any:
            validate_participationtag(vctx, location, ptag)

    if hasattr(arule, "if_has_participation_tags_all"):
        for ptag in arule.if_has_participation_tags_all:
            validate_participationtag(vctx, location, ptag)

    if hasattr(arule, "if_in_facility"):
        validate_facility(vctx, location, arule.if_in_facility)

    if hasattr(arule, "if_has_tag"):
        if arule.if_has_tag is not None:
            validate_identifier(vctx, "%s: if_has_tag" % location,
                    arule.if_has_tag,
                    warning_only=True)

        if not (arule.if_has_tag is None or arule.if_has_tag in tags):
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': arule.if_has_tag})

    if hasattr(arule, "if_expiration_mode"):
        if arule.if_expiration_mode not in dict(
                FLOW_SESSION_EXPIRATION_MODE_CHOICES):
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("invalid expiration mode '%(expiremode)s'"))
                    % {
                        'location': location,
                        'expiremode': arule.if_expiration_mode})

    for j, perm in enumerate(arule.permissions):
        validate_flow_permission(
                vctx,
                "%s, permission %d" % (location, j+1),
                perm)

    if hasattr(arule, "if_in_progress") and not arule.if_in_progress:
        from course.constants import flow_permission
        if (
                flow_permission.submit_answer in arule.permissions
                or flow_permission.end_session in arule.permissions):
            vctx.add_warning(location,
                    _("Rule specifies 'submit_answer' or 'end_session' "
                        "permissions for non-in-progress flow. These "
                        "permissions will be ignored."))


def validate_session_grading_rule(
        vctx,  # type: ValidationContext
        location,  # type: Text
        grule,  # type: Any
        tags,  # type: List[Text]
        grade_identifier,  # type: Optional[Text]
        ):
    # type: (...) -> bool

    """
    :returns: whether the rule only applies conditionally
    """

    validate_struct(
            vctx, location, grule,
            required_attrs=[
                ],
            allowed_attrs=[
                ("if_has_role", list),
                ("if_has_participation_tags_any", list),
                ("if_has_participation_tags_all", list),
                ("if_has_tag", (str, type(None))),
                ("if_started_before", datespec_types),
                ("if_completed_before", datespec_types),

                ("credit_percent", (int, float)),
                ("use_last_activity_as_completion_time", bool),
                ("due", datespec_types),
                ("generates_grade", bool),
                ("description", str),

                ("max_points", (int, float)),
                ("max_points_enforced_cap", (int, float)),
                ("bonus_points", (int, float)),

                # legacy
                ("grade_identifier", (type(None), str)),
                ("grade_aggregation_strategy", str),
                ]
            )

    if hasattr(grule, "grade_identifier"):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("'grade_identifier' attribute found. "
                        "This attribute is no longer allowed here "
                        "and should be moved upward into the 'rules' "
                        "block."))
                % {"location": location})

    if hasattr(grule, "grade_aggregation_strategy"):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("'grade_aggregation_strategy' attribute found. "
                        "This attribute is no longer allowed here "
                        "and should be moved upward into the 'rules' "
                        "block."))
                % {"location": location})

    has_conditionals = False

    if hasattr(grule, "if_started_before"):
        vctx.encounter_datespec(location, grule.if_started_before)
        has_conditionals = True

    if hasattr(grule, "if_completed_before"):
        vctx.encounter_datespec(location, grule.if_completed_before)
        has_conditionals = True

    if hasattr(grule, "if_has_role"):
        for j, role in enumerate(grule.if_has_role):
            validate_role(
                    vctx,
                    "%s, role %d" % (location, j+1),
                    role)
        has_conditionals = True

    if hasattr(grule, "if_has_participation_tags_any"):
        for ptag in grule.if_has_participation_tags_any:
            validate_participationtag(vctx, location, ptag)
        has_conditionals = True

    if hasattr(grule, "if_has_participation_tags_all"):
        for ptag in grule.if_has_participation_tags_all:
            validate_participationtag(vctx, location, ptag)
        has_conditionals = True

    if hasattr(grule, "if_has_tag"):
        if grule.if_has_tag is not None:
            validate_identifier(vctx, "%s: if_has_tag" % location,
                    grule.if_has_tag,
                    warning_only=True)

        if not (grule.if_has_tag is None or grule.if_has_tag in tags):
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': grule.if_has_tag})
        has_conditionals = True

    if hasattr(grule, "due"):
        vctx.encounter_datespec(location, grule.due)

    if (getattr(grule, "generates_grade", True)
            and grade_identifier is None):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("'generates_grade' is true, but no 'grade_identifier'"
                        "is given."))
                % {"location": location})

    return has_conditionals


def validate_flow_rules(vctx, location, rules):
    validate_struct(
            vctx,
            location + ", rules",
            rules,
            required_attrs=[
                ("access", list),
                ],
            allowed_attrs=[
                # may not start with an underscore
                ("start", list),
                ("grading", list),
                ("tags", list),

                ("grade_identifier", (type(None), str)),
                ("grade_aggregation_strategy", str),
                ]
            )

    if not hasattr(rules, "grade_identifier"):
        error_msg = _("'rules' block does not have a grade_identifier "
                     "attribute.")

        # for backward compatibility
        if hasattr(rules, "grading"):
            if hasattr(rules.grading, "grade_identifier"):
                error_msg = string_concat(
                    error_msg,
                    _(" This attribute needs to be moved out of "
                      "the lower-level 'grading' rules block and into "
                      "the 'rules' block itself."))
        raise ValidationError(
                string_concat("%(location)s: ", error_msg)
                % {'location': location})

    tags = getattr(rules, "tags", [])

    for i, tag in enumerate(tags):
        validate_identifier(vctx, "%s: tag %d" % (location, i+1), tag)

    # {{{ validate new-session rules

    if hasattr(rules, "start"):
        for i, nrule in enumerate(rules.start):
            validate_session_start_rule(
                    vctx, "%s, rules/start %d" % (location,  i+1),
                    nrule, tags)

    # }}}

    # {{{ validate access rules

    for i, arule in enumerate(rules.access):
        validate_session_access_rule(
                vctx,
                location="%s, rules/access #%d"
                % (location,  i+1), arule=arule, tags=tags)

    # }}}

    # {{{ grade_id

    if rules.grade_identifier:
        validate_identifier(vctx, "%s: grade_identifier" % location,
                rules.grade_identifier)
        if not hasattr(rules, "grade_aggregation_strategy"):
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("flows that have a grade "
                            "identifier ('%(identifier)s') "
                            "must have grading rules with a "
                            "grade_aggregation_strategy"))
                    % {
                        'location': location,
                        'identifier': rules.grade_identifier})

    from course.constants import GRADE_AGGREGATION_STRATEGY_CHOICES
    if (
            hasattr(rules, "grade_aggregation_strategy")
            and rules.grade_aggregation_strategy
            not in dict(GRADE_AGGREGATION_STRATEGY_CHOICES)):
        raise ValidationError(
                string_concat("%s: ",
                    _("invalid grade aggregation strategy"),
                    ": %s" % rules.grade_aggregation_strategy)
                % location)

    # }}}

    # {{{ validate grading rules

    if not hasattr(rules, "grading"):
        if rules.grade_identifier is not None:
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("'grading' block is required if grade_identifier "
                            "is not null/None."))
                    % {'location': location})

    else:
        has_conditionals = None

        if len(rules.grading) == 0:
            raise ValidationError(
                    string_concat(
                        "%s, ",
                        _("rules/grading: "
                            "may not be an empty list"))
                    % location)

        for i, grule in enumerate(rules.grading):
            has_conditionals = validate_session_grading_rule(
                    vctx,
                    location="%s, rules/grading #%d"
                    % (location,  i+1), grule=grule, tags=tags,
                    grade_identifier=rules.grade_identifier)

        if has_conditionals:
            raise ValidationError(
                    string_concat(
                        "%s, ",
                        _("rules/grading: "
                            "last grading rule must be unconditional"))
                    % location)

    # }}}


def validate_flow_permission(vctx, location, permission):
    # type: (ValidationContext, Text, Text) -> None

    from course.constants import FLOW_PERMISSION_CHOICES
    if permission == "modify":
        vctx.add_warning(location, _("Uses deprecated 'modify' permission--"
                "replace by 'submit_answer' and 'end_session'"))
        return

    if permission == "see_answer":
        vctx.add_warning(location,
                _("Uses deprecated 'see_answer' permission--"
                "replace by 'see_answer_after_submission'"))
        return

    if permission not in dict(FLOW_PERMISSION_CHOICES):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("invalid flow permission '%(permission)s'"))
                % {'location': location, 'permission': permission})

# }}}


def validate_flow_desc(vctx, location, flow_desc):
    validate_struct(
            vctx,
            location,
            flow_desc,
            required_attrs=[
                ("title", str),
                ("description", "markup"),
                ],
            allowed_attrs=[
                ("completion_text", "markup"),
                ("rules", Struct),
                ("groups", list),
                ("pages", list),
                ("notify_on_submit", list),

                # deprecated (moved to grading rule)
                ("max_points", (int, float)),
                ("max_points_enforced_cap", (int, float)),
                ("bonus_points", (int, float)),
                ]
            )

    if hasattr(flow_desc, "rules"):
        validate_flow_rules(vctx, location, flow_desc.rules)

    # {{{ check for presence of 'groups' or 'pages'

    if (
            (not hasattr(flow_desc, "groups") and not hasattr(flow_desc, "pages"))
            or (hasattr(flow_desc, "groups") and hasattr(flow_desc, "pages"))):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("must have either 'groups' or 'pages'"))
                % {'location': location})

    # }}}

    if hasattr(flow_desc, "pages"):
        from course.content import normalize_flow_desc
        flow_desc = normalize_flow_desc(flow_desc)

        assert not hasattr(flow_desc, "pages")
        assert hasattr(flow_desc, "groups")

    # {{{ check for non-emptiness

    flow_has_page = False
    for i, grp in enumerate(flow_desc.groups):
        group_has_page = False

        if not isinstance(grp.pages, list):
            raise ValidationError(
                    string_concat(
                        "%(location)s, ",
                        _("group %(group_index)d ('%(group_id)s'): "
                            "'pages' is not a list"))
                    % {
                        'location': location,
                        'group_index': i+1,
                        'group_id': grp.id})

        for page in grp.pages:
            group_has_page = flow_has_page = True
            break

        if not group_has_page:
            raise ValidationError(
                    string_concat(
                        "%(location)s, ",
                        _("group %(group_index)d ('%(group_id)s'): "
                            "no pages found"))
                    % {
                        'location': location,
                        'group_index': i+1,
                        'group_id': grp.id})

    if not flow_has_page:
        raise ValidationError(_("%s: no pages found")
                % location)

    # }}}

    # {{{ check group id uniqueness

    group_ids = set()

    for grp in flow_desc.groups:
        if grp.id in group_ids:
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("group id '%(group_id)s' not unique"))
                    % {'location': location, 'group_id': grp.id})

        group_ids.add(grp.id)

    # }}}

    for i, grp in enumerate(flow_desc.groups):
        validate_flow_group(vctx, "%s, group %d ('%s')"
                % (location, i+1, grp.id),
                grp)

    validate_markup(vctx, location, flow_desc.description)
    if hasattr(flow_desc, "completion_text"):
        validate_markup(vctx, location, flow_desc.completion_text)

    if hasattr(flow_desc, "notify_on_submit"):
        for i, item in enumerate(flow_desc.notify_on_submit):
            if not isinstance(item, str):
                raise ValidationError(
                        string_concat(
                            "%s, ",
                            _("notify_on_submit: item %d is not a string"))
                        % (location, i+1))

    for attr in ["max_points", "max_points_enforced_cap", "bonus_points"]:
        if hasattr(flow_desc, attr):
            vctx.add_warning(location,
                    _("Attribute '%s' is deprecated as part of a flow. "
                    "Specify it as part of a grading rule instead.")
                    % attr)

# }}}


# {{{ calendar validation

def validate_calendar_desc_struct(vctx, location, events_desc):
    validate_struct(
            vctx,
            location,
            events_desc,
            required_attrs=[
                ],
            allowed_attrs=[
                ("event_kinds", Struct),
                ("events", Struct),
                ]
            )

    if hasattr(events_desc, "event_kinds"):
        for event_kind_name in events_desc.event_kinds._field_names:
            event_kind = getattr(events_desc.event_kinds, event_kind_name)

            validate_struct(
                    vctx,
                    "%s, event kind '%s'" % (location, event_kind_name),
                    event_kind,
                    required_attrs=[
                        ],
                    allowed_attrs=[
                        ("color", str),
                        ("title", str),
                        ]
                    )

    if hasattr(events_desc, "events"):
        for event_name in events_desc.events._field_names:
            event_desc = getattr(events_desc.events, event_name)

            validate_struct(
                    vctx,
                    "%s, event '%s'" % (location, event_name),
                    event_desc,
                    required_attrs=[
                        ],
                    allowed_attrs=[
                        ("color", str),
                        ("title", str),
                        ("description", "markup"),
                        ("show_description_from", datespec_types),
                        ("show_description_until", datespec_types),
                        ]
                    )

            if hasattr(event_desc, "show_description_from"):
                vctx.encounter_datespec(location, event_desc.show_description_from)

            if hasattr(event_desc, "show_description_until"):
                vctx.encounter_datespec(location, event_desc.show_description_until)

# }}}


def get_yaml_from_repo_safely(repo, full_name, commit_sha):
    from course.content import get_yaml_from_repo
    try:
        return get_yaml_from_repo(
                repo=repo, full_name=full_name, commit_sha=commit_sha,
                cached=False)
    except Exception:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        raise ValidationError(
                "%(fullname)s: %(err_type)s: %(err_str)s" % {
                    'fullname': full_name,
                    "err_type": tp.__name__,
                    "err_str": str(e)})


def check_attributes_yml(vctx, repo, path, tree, access_kinds):
    # type: (ValidationContext, Repo_ish, Text, Any, List[Text]) -> None
    """
    This function reads the .attributes.yml file and checks
    that each item for each header is a string

    Example::

        # this validates
        unenrolled:
            - test1.pdf
        student:
            - test2.pdf

        # this does not validate
        unenrolled:
            - test1.pdf
        student:
            - test2.pdf
            - 42
    """
    from course.content import get_true_repo_and_path
    true_repo, path = get_true_repo_and_path(repo, path)

    # {{{ analyze attributes file

    try:
        dummy, attr_blob_sha = tree[ATTRIBUTES_FILENAME.encode()]
    except KeyError:
        # no .attributes.yml here
        pass
    except ValueError:
        # the path root only contains a directory
        pass
    else:
        from relate.utils import dict_to_struct
        from yaml import safe_load as load_yaml

        yaml_data = load_yaml(true_repo[attr_blob_sha].data)  # type: ignore
        att_yml = dict_to_struct(yaml_data)

        if path:
            loc = path + "/" + ATTRIBUTES_FILENAME
        else:
            loc = ATTRIBUTES_FILENAME

        validate_struct(vctx, loc, att_yml,
                        required_attrs=[],
                        allowed_attrs=[(role, list) for role in access_kinds])

        if hasattr(att_yml, "public"):
            vctx.add_warning(loc,
                    _("Access class 'public' is deprecated. Use 'unenrolled' "
                        "instead."))

        if hasattr(att_yml, "public") and hasattr(att_yml, "unenrolled"):
            raise ValidationError(
                _("%s: access classes 'public' and 'unenrolled' may not "
                    "exist simultaneously.")
                % (loc))

        for access_kind in access_kinds:
            if hasattr(att_yml, access_kind):
                for i, l in enumerate(getattr(att_yml, access_kind)):
                    if not isinstance(l, str):
                        raise ValidationError(
                            "%s: entry %d in '%s' is not a string"
                            % (loc, i+1, access_kind))

    # }}}

    # {{{ analyze gitignore

    gitignore_lines = []  # type: List[Text]

    try:
        dummy, gitignore_sha = tree[b".gitignore"]
    except KeyError:
        # no .gitignore here
        pass
    except ValueError:
        # the path root only contains a directory
        pass
    else:
        gitignore_lines = true_repo[gitignore_sha].data.decode("utf-8").split("\n")

    # }}}

    import stat
    from fnmatch import fnmatchcase

    for entry in tree.items():
        entry_name = entry.path.decode("utf-8")
        if any(fnmatchcase(entry_name, line) for line in gitignore_lines):
            continue

        if path:
            subpath = path+"/"+entry_name
        else:
            subpath = entry_name

        if stat.S_ISDIR(entry.mode):
            dummy, blob_sha = tree[entry.path]
            subtree = true_repo[blob_sha]
            check_attributes_yml(vctx, true_repo, subpath, subtree, access_kinds)


# {{{ check whether flow grade identifiers were changed in sketchy ways

def check_grade_identifier_link(
        vctx, location, course, flow_id, flow_grade_identifier):

    from course.models import GradingOpportunity
    for bad_gopp in (
            GradingOpportunity.objects
            .filter(
                course=course,
                identifier=flow_grade_identifier)
            .exclude(flow_id=flow_id)):
        # 0 or 1 trips through this loop because of uniqueness

        raise ValidationError(
                _(
                    "{location}: existing grading opportunity with identifier "
                    "'{grade_identifier}' refers to flow '{other_flow_id}', however "
                    "flow code in this flow ('{new_flow_id}') specifies the same "
                    "grade identifier. "
                    "(Have you renamed the flow? If so, edit the grading "
                    "opportunity to match.)")
                .format(
                    location=location,
                    grade_identifier=flow_grade_identifier,
                    other_flow_id=bad_gopp.flow_id,
                    new_flow_id=flow_id,
                    new_grade_identifier=flow_grade_identifier))

# }}}


# {{{ check whether page types were changed

def check_for_page_type_changes(vctx, location, course, flow_id, flow_desc):
    from course.content import normalize_flow_desc
    n_flow_desc = normalize_flow_desc(flow_desc)

    from course.models import FlowPageData
    for grp in n_flow_desc.groups:  # pragma: no branch
        for page_desc in grp.pages:  # pragma: no branch
            fpd_with_mismatched_page_types = list(
                    FlowPageData.objects
                    .filter(
                        flow_session__course=course,
                        flow_session__flow_id=flow_id,
                        group_id=grp.id,
                        page_id=page_desc.id)
                    .exclude(page_type=None)
                    .exclude(page_type=page_desc.type)
                    [0:1])

            if fpd_with_mismatched_page_types:
                mismatched_fpd, = fpd_with_mismatched_page_types
                raise ValidationError(
                        _("%(loc)s, group '%(group)s', page '%(page)s': "
                            "page type ('%(type_new)s') differs from "
                            "type used in database ('%(type_old)s')")
                        % {"loc": location, "group": grp.id,
                            "page": page_desc.id,
                            "type_new": page_desc.type,
                            "type_old": mismatched_fpd.page_type})

# }}}


def validate_flow_id(vctx, location, flow_id):
    # type: (ValidationContext, Text, Text) -> None

    from course.constants import FLOW_ID_REGEX
    match = re.match("^" + FLOW_ID_REGEX + "$", flow_id)
    if match is None:
        raise ValidationError(
            string_concat("%s: ",
                          _("invalid flow name. "
                            "Flow names may only contain (roman) "
                            "letters, numbers, "
                            "dashes and underscores."))
            % location)


def validate_static_page_name(vctx, location, page_name):
    # type: (ValidationContext, Text, Text) -> None

    from course.constants import STATICPAGE_PATH_REGEX
    match = re.match("^" + STATICPAGE_PATH_REGEX + "$", page_name)
    if match is None:
        raise ValidationError(
            string_concat("%s: ",
                          _(
                              "invalid page name. "
                              "Page names may only contain "
                              "alphanumeric characters (any language) "
                              "and hyphens."
                          ))
            % location)


def validate_course_content(repo, course_file, events_file,
        validate_sha, course=None):
    vctx = ValidationContext(
            repo=repo,
            commit_sha=validate_sha,
            course=course)

    course_desc = get_yaml_from_repo_safely(repo, course_file,
            commit_sha=validate_sha)

    validate_staticpage_desc(vctx, course_file, course_desc)

    try:
        from course.content import get_yaml_from_repo
        events_desc = get_yaml_from_repo(repo, events_file,
                commit_sha=validate_sha, cached=False)
    except ObjectDoesNotExist:
        if events_file != "events.yml":
            vctx.add_warning(
                    _("Events file"),
                    _("Your course repository does not have an events "
                        "file named '%s'.")
                    % events_file)
        else:
            # That's OK--no calendar info.
            pass
    else:
        validate_calendar_desc_struct(vctx, events_file, events_desc)

    if vctx.course is not None:
        from course.models import (
                ParticipationPermission,
                ParticipationRolePermission)
        access_kinds = frozenset(
                ParticipationPermission.objects
                .filter(
                    participation__course=vctx.course,
                    permission=pperm.access_files_for,
                    )
                .values_list("argument", flat=True)) | frozenset(
                        ParticipationRolePermission.objects
                        .filter(
                            role__course=vctx.course,
                            permission=pperm.access_files_for,
                            )
                        .values_list("argument", flat=True))

        access_kinds = frozenset(k for k in access_kinds if k is not None)

    else:
        access_kinds = DEFAULT_ACCESS_KINDS

    check_attributes_yml(
            vctx, repo, "",
            get_repo_blob(repo, "", validate_sha),
            access_kinds)

    try:
        flows_tree = get_repo_blob(repo, "media", validate_sha)
    except ObjectDoesNotExist:
        # That's great--no media directory.
        pass
    else:
        vctx.add_warning(
                'media/', _(
                    "Your course repository has a 'media/' directory. "
                    "Linking to media files using 'media:' is discouraged. "
                    "Use the 'repo:' and 'repocur:' linkng schemes instead."))

    # {{{ flows

    try:
        flows_tree = get_repo_blob(repo, "flows", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        used_grade_identifiers = set()

        for entry in flows_tree.items():
            entry_path = entry.path.decode("utf-8")
            if not entry_path.endswith(".yml"):
                continue

            flow_id = entry_path[:-4]
            location = entry_path
            validate_flow_id(vctx, location, flow_id)

            location = "flows/%s" % entry_path
            flow_desc = get_yaml_from_repo_safely(repo, location,
                    commit_sha=validate_sha)

            validate_flow_desc(vctx, location, flow_desc)

            # {{{ check grade_identifier

            flow_grade_identifier = None
            if hasattr(flow_desc, "rules"):
                flow_grade_identifier = getattr(
                        flow_desc.rules, "grade_identifier", None)

            if (
                    flow_grade_identifier is not None
                    and set([flow_grade_identifier]) & used_grade_identifiers):
                raise ValidationError(
                        string_concat("%s: ",
                                      _("flow uses the same grade_identifier "
                                        "as another flow"))
                        % location)

            used_grade_identifiers.add(flow_grade_identifier)

            if (course is not None
                    and flow_grade_identifier is not None):
                check_grade_identifier_link(
                        vctx, location, course, flow_id, flow_grade_identifier)

            # }}}

            if course is not None:
                check_for_page_type_changes(
                        vctx, location, course, flow_id, flow_desc)

    # }}}

    # {{{ static pages

    try:
        pages_tree = get_repo_blob(repo, "staticpages", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in pages_tree.items():
            entry_path = entry.path.decode("utf-8")
            if not entry_path.endswith(".yml"):
                continue

            page_name = entry_path[:-4]
            location = entry_path
            validate_static_page_name(vctx, location, page_name)

            location = "staticpages/%s" % entry_path
            page_desc = get_yaml_from_repo_safely(repo, location,
                    commit_sha=validate_sha)

            validate_staticpage_desc(vctx, location, page_desc)

    # }}}

    return vctx.warnings


# {{{ validation script support

class FileSystemFakeRepo(object):  # pragma: no cover
    def __init__(self, root):
        self.root = root
        assert isinstance(self.root, bytes)

    def controldir(self):
        return self.root

    def __getitem__(self, sha):
        return sha

    def __str__(self):
        return "<FAKEREPO:%s>" % self.root

    def decode(self):
        return self

    @property
    def tree(self):
        return FileSystemFakeRepoTree(self.root)


class FileSystemFakeRepoTreeEntry(object):  # pragma: no cover
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode


class FileSystemFakeRepoTree(object):  # pragma: no cover
    def __init__(self, root):
        self.root = root
        assert isinstance(self.root, bytes)

    def __getitem__(self, name):
        if not name:
            raise KeyError("<empty filename>")

        from os.path import join, isdir, exists
        name = join(self.root, name)

        if not exists(name):
            raise KeyError(name)

        # returns mode, "sha"
        if isdir(name):
            return None, FileSystemFakeRepoTree(name)
        else:
            return None, FileSystemFakeRepoFile(name)

    def items(self):
        import os
        return [
                FileSystemFakeRepoTreeEntry(
                    path=n,
                    mode=os.stat(os.path.join(self.root, n)).st_mode)
                for n in os.listdir(self.root)]


class FileSystemFakeRepoFile(object):  # pragma: no cover
    def __init__(self, name):
        self.name = name

    @property
    def data(self):
        with open(self.name, "rb") as inf:
            return inf.read()


def validate_course_on_filesystem(
        root, course_file, events_file):  # pragma: no cover
    fake_repo = FileSystemFakeRepo(root.encode("utf-8"))
    warnings = validate_course_content(
            fake_repo,
            course_file, events_file,
            validate_sha=fake_repo, course=None)

    if warnings:
        print(_("WARNINGS: "))
        for w in warnings:
            print("***", w.location, w.text)

    return bool(warnings)

# }}}

# vim: foldmethod=marker
