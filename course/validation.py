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
import six
import sys

from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import escape
from django.utils.translation import (
        ugettext_lazy as _, ugettext, string_concat)

from course.content import get_repo_blob
from relate.utils import Struct


# {{{ validation tools

class ValidationError(RuntimeError):
    pass


ID_RE = re.compile(r"^[\w]+$")


def validate_identifier(ctx, location, s, warning_only=False):
    if not ID_RE.match(s):

        if warning_only:
            msg = (string_concat(
                        _("invalid identifier"),
                        " '%(string)s'")
                    % {'location': location, 'string': s})

            ctx.add_warning(location, msg)
        else:
            msg = (string_concat(
                        "%(location)s: ",
                        _("invalid identifier"),
                        " '%(string)s'")
                    % {'location': location, 'string': s})

            raise ValidationError(msg)


def validate_role(location, role):
    from course.constants import participation_role

    if role not in [
            participation_role.instructor,
            participation_role.teaching_assistant,
            participation_role.student,
            participation_role.unenrolled,
            ]:
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("invalid role '%(role)s'"))
                % {'location': location, 'role': role})


def validate_struct(ctx, location, obj, required_attrs, allowed_attrs):
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

                if allowed_types == str:
                    # Love you, too, Python 2.
                    allowed_types = (str, unicode)

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
                    validate_markup(ctx, "%s: attribute %s" % (location, attr), val)

    if present_attrs:
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("extraneous attribute(s) '%(attr)s'"))
                % {'location': location, 'attr': ",".join(present_attrs)})


datespec_types = (datetime.date, six.string_types, datetime.datetime)

# }}}


class ValidationWarning(object):
    def __init__(self, location, text):
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

    def __init__(self, repo, commit_sha, course=None):
        self.repo = repo
        self.commit_sha = commit_sha
        self.course = course

        self.warnings = []

    def encounter_datespec(self, location, datespec):
        from course.content import parse_date_spec
        parse_date_spec(self.course, datespec, vctx=self, location=location)

    def add_warning(self, *args, **kwargs):
        self.warnings.append(ValidationWarning(*args, **kwargs))


# {{{ course page validation

def validate_markup(ctx, location, markup_str):
    def reverse_func(*args, **kwargs):
        pass

    from course.content import markup_to_html
    try:
        markup_to_html(
                course=None,
                repo=ctx.repo,
                commit_sha=ctx.commit_sha,
                text=markup_str,
                reverse_func=reverse_func,
                validate_only=True)
    except:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        raise ValidationError(
                "%(location)s: %(err_type)s: %(err_str)s" % {
                    'location': location,
                    "err_type": tp.__name__,
                    "err_str": str(e)})


def validate_chunk_rule(ctx, location, chunk_rule):
    validate_struct(
            ctx,
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

                ("start", datespec_types),
                ("end", datespec_types),
                ("roles", list),

                ("shown", bool),
            ])

    if hasattr(chunk_rule, "if_after"):
        ctx.encounter_datespec(location, chunk_rule.if_after)

    if hasattr(chunk_rule, "if_before"):
        ctx.encounter_datespec(location, chunk_rule.if_before)

    if hasattr(chunk_rule, "if_has_role"):
        for role in chunk_rule.if_has_role:
            validate_role(location, role)

    # {{{ deprecated

    if hasattr(chunk_rule, "start"):
        ctx.add_warning(location, _("Uses deprecated 'start' attribute--"
                "use 'if_after' instead"))

        ctx.encounter_datespec(location, chunk_rule.start)

    if hasattr(chunk_rule, "end"):
        ctx.add_warning(location, _("Uses deprecated 'end' attribute--"
                "use 'if_before' instead"))

        ctx.encounter_datespec(location, chunk_rule.end)

    if hasattr(chunk_rule, "roles"):
        ctx.add_warning(location, _("Uses deprecated 'roles' attribute--"
                "use 'if_has_role' instead"))

        for role in chunk_rule.roles:
            validate_role(location, role)

    # }}}


def validate_chunk(ctx, location, chunk):
    validate_struct(
            ctx,
            location,
            chunk,
            required_attrs=[
                ("title", str),
                ("id", str),
                ("rules", list),
                ("content", "markup"),
                ],
            allowed_attrs=[]
            )

    for i, rule in enumerate(chunk.rules):
        validate_chunk_rule(ctx,
                "%s, rule %d" % (location, i+1),
                rule)


def validate_course_desc_struct(ctx, location, course_desc):
    validate_struct(
            ctx,
            location,
            course_desc,
            required_attrs=[
                ("name", str),
                ("number", str),
                ("run", str),
                ("chunks", list),
                ],
            allowed_attrs=[
                ("grade_summary_code", str),
                ]
            )

    for i, chunk in enumerate(course_desc.chunks):
        validate_chunk(ctx,
                "%s, chunk %d ('%s')"
                % (location, i+1, getattr(chunk, "id", None)),
                chunk)

    # {{{ check chunk id uniqueness

    chunk_ids = set()

    for chunk in course_desc.chunks:
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

def validate_flow_page(ctx, location, page_desc):
    if not hasattr(page_desc, "id"):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    ugettext("flow page has no ID"))
                % location)

    validate_identifier(ctx, location, page_desc.id)

    from course.content import get_flow_page_class
    try:
        class_ = get_flow_page_class(ctx.repo, page_desc.type, ctx.commit_sha)
        class_(ctx, location, page_desc)
    except ValidationError:
        raise
    except:
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
                    "err_type": tp.__name__,
                    "err_str": str(e),
                    'format_exc': format_exc()})


def validate_flow_group(ctx, location, grp):
    validate_struct(
            ctx,
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

    for i, page_desc in enumerate(grp.pages):
        validate_flow_page(
                ctx,
                "%s, page %d ('%s')"
                % (location, i+1, getattr(page_desc, "id", None)),
                page_desc)

    if len(grp.pages) == 0:
        raise ValidationError(
                string_concat(
                    "%(location)s, ",
                    _("group '%(group_id)s': group is empty"))
                % {'location': location, 'group_id': grp.id})

    if hasattr(grp, "max_page_count") and grp.max_page_count <= 0:
        raise ValidationError(
                string_concat(
                    "%(location)s, ",
                    _("group '%(group_id)s': "
                        "max_page_count is not positive"))
                % {'location': location, 'group_id': grp.id})

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

    validate_identifier(ctx, location, grp.id)


# {{{ flow access rules

def validate_session_start_rule(ctx, location, nrule, tags):
    validate_struct(
            ctx, location, nrule,
            required_attrs=[],
            allowed_attrs=[
                ("if_after", datespec_types),
                ("if_before", datespec_types),
                ("if_has_role", list),
                ("if_in_facility", str),
                ("if_has_in_progress_session", bool),
                ("if_has_session_tagged", (str, unicode, type(None))),
                ("if_has_fewer_sessions_than", int),
                ("if_has_fewer_tagged_sessions_than", int),
                ("tag_session", (str, unicode, type(None))),
                ("may_start_new_session", bool),
                ("may_list_existing_sessions", bool),
                ]
            )

    if hasattr(nrule, "if_after"):
        ctx.encounter_datespec(location, nrule.if_after)
    if hasattr(nrule, "if_before"):
        ctx.encounter_datespec(location, nrule.if_before)
    if hasattr(nrule, "if_has_role"):
        for j, role in enumerate(nrule.if_has_role):
            validate_role(
                    "%s, role %d" % (location, j+1),
                    role)

    if hasattr(nrule, "if_has_session_tagged"):
        if nrule.if_has_session_tagged is not None:
            validate_identifier(ctx, "%s: if_has_session_tagged" % location,
                    nrule.if_has_session_tagged)

    if not hasattr(nrule, "may_start_new_session"):
        ctx.add_warning(
                location+", rules",
                _("attribute 'may_start_new_session' is not present"))
    if not hasattr(nrule, "may_list_existing_sessions"):
        ctx.add_warning(
                location+", rules",
                _("attribute 'may_list_existing_sessions' is not present"))

    if hasattr(nrule, "tag_session"):
        if nrule.tag_session is not None:
            validate_identifier(ctx, "%s: tag_session" % location,
                    nrule.tag_session,
                    warning_only=True)

        if not (nrule.tag_session is None or nrule.tag_session in tags):
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': nrule.tag_session})


def validate_session_access_rule(ctx, location, arule, tags):
    validate_struct(
            ctx, location, arule,
            required_attrs=[
                ("permissions", list),
                ],
            allowed_attrs=[
                ("if_after", datespec_types),
                ("if_before", datespec_types),
                ("if_has_role", list),
                ("if_in_facility", str),
                ("if_has_tag", (str, unicode, type(None))),
                ("if_in_progress", bool),
                ("if_completed_before", datespec_types),
                ("if_expiration_mode", str),
                ("message", datespec_types),
                ]
            )

    if hasattr(arule, "if_after"):
        ctx.encounter_datespec(location, arule.if_after)
    if hasattr(arule, "if_before"):
        ctx.encounter_datespec(location, arule.if_before)
    if hasattr(arule, "if_completed_before"):
        ctx.encounter_datespec(location, arule.if_completed_before)

    if hasattr(arule, "if_has_role"):
        for j, role in enumerate(arule.if_has_role):
            validate_role(
                    "%s, role %d" % (location, j+1),
                    role)
    if hasattr(arule, "if_has_tag"):
        if not (arule.if_has_tag is None or arule.if_has_tag in tags):
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': arule.if_has_tag})

    if hasattr(arule, "if_expiration_mode"):
        from course.constants import FLOW_SESSION_EXPIRATION_MODE_CHOICES
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
                ctx,
                "%s, permission %d" % (location, j+1),
                perm)


def validate_session_grading_rule(ctx, location, grule, tags):
    """
    :returns: whether the rule only applies conditionally
    """

    validate_struct(
            ctx, location, grule,
            required_attrs=[
                ("grade_identifier", (type(None), str)),
                ],
            allowed_attrs=[
                ("if_has_role", list),
                ("if_has_tag", (str, unicode, type(None))),
                ("if_completed_before", datespec_types),

                ("credit_percent", (int, float)),
                ("due", datespec_types),
                ("grade_aggregation_strategy", str),
                ("description", str),
                ]
            )

    has_conditionals = False

    if hasattr(grule, "if_completed_before"):
        ctx.encounter_datespec(location, grule.if_completed_before)
        has_conditionals = True

    if hasattr(grule, "if_has_role"):
        for j, role in enumerate(grule.if_has_role):
            validate_role(
                    "%s, role %d" % (location, j+1),
                    role)
        has_conditionals = True

    if hasattr(grule, "if_has_tag"):
        if not (grule.if_has_tag is None or grule.if_has_tag in tags):
            raise ValidationError(
                    string_concat(
                        "%(locatioin)s: ",
                        _("invalid tag '%(tag)s'"))
                    % {'location': location, 'tag': grule.if_has_tag})
        has_conditionals = True

    if hasattr(grule, "due"):
        ctx.encounter_datespec(location, grule.due)

    if grule.grade_identifier:
        validate_identifier(ctx, "%s: grade_identifier" % location,
                grule.grade_identifier)
        if not hasattr(grule, "grade_aggregation_strategy"):
            raise ValidationError(
                    string_concat("%(location)s: ",
                        _("grading rule that have a grade "
                            "identifier (%(type)s: %(identifier)s) "
                            "must have a grade_aggregation_strategy"))
                    % {
                        'location': location,
                        'type': type(grule.grade_identifier),
                        'identifier': grule.grade_identifier})
        from course.constants import GRADE_AGGREGATION_STRATEGY_CHOICES
        if grule.grade_aggregation_strategy not in \
                dict(GRADE_AGGREGATION_STRATEGY_CHOICES):
            raise ValidationError(
                    string_concat("%s: ",
                        _("invalid grade aggregation strategy"))
                    % location)

    return has_conditionals


def validate_flow_rules(ctx, location, rules):
    validate_struct(
            ctx,
            location + ", rules",
            rules,
            required_attrs=[
                ("access", list),
                ("grading", list),
                ],
            allowed_attrs=[
                # may not start with an underscore
                ("start", list),
                ("tags", list),
                ]
            )

    tags = getattr(rules, "tags", [])

    for i, tag in enumerate(tags):
        validate_identifier(ctx, "%s: tag %d" % (location, i+1), tag)

    # {{{ validate new-session rules

    if hasattr(rules, "start"):
        for i, nrule in enumerate(rules.start):
            validate_session_start_rule(
                    ctx, "%s, rules/start %d" % (location,  i+1),
                    nrule, tags)

    # }}}

    # {{{ validate access rules

    for i, arule in enumerate(rules.access):
        validate_session_access_rule(
                ctx,
                location="%s, rules/access #%d"
                % (location,  i+1), arule=arule, tags=tags)

    # }}}

    # {{{ validate grading rules

    has_conditionals = None

    for i, grule in enumerate(rules.grading):
        has_conditionals = validate_session_grading_rule(
                ctx,
                location="%s, rules/grading #%d"
                % (location,  i+1), grule=grule, tags=tags)

    if has_conditionals:
        raise ValidationError(
                string_concat(
                    "%s, ",
                    _("rules/grading: "
                        "last grading rule must be unconditional"))
                % location)

    # }}}


def validate_flow_permission(ctx, location, permission):
    from course.constants import FLOW_PERMISSION_CHOICES
    if permission == "modify":
        ctx.add_warning(location, _("Uses deprecated 'modify' permission--"
                "replace by 'submit_answer' and 'end_session'"))
        return

    if permission == "see_answer":
        ctx.add_warning(location,
                _("Uses deprecated 'see_answer' permission--"
                "replace by 'see_answer_after_submission'"))
        return

    if permission not in dict(FLOW_PERMISSION_CHOICES):
        raise ValidationError(
                string_concat("%(location)s: ",
                    _("invalid flow permission '%(permission)s'"))
                % {'location': location, 'permission': permission})

# }}}


def validate_flow_desc(ctx, location, flow_desc):
    validate_struct(
            ctx,
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
                ]
            )

    if hasattr(flow_desc, "rules"):
        validate_flow_rules(ctx, location, flow_desc.rules)

    # {{{ check for presence of 'groups' or 'pages'

    if (
            (not hasattr(flow_desc, "groups") and not hasattr(flow_desc, "pages"))
            or
            (hasattr(flow_desc, "groups") and hasattr(flow_desc, "pages"))):
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

        for page in grp.pages:
            group_has_page = flow_has_page = True
            break

        if not group_has_page:
            raise ValidationError(
                    string_concat(
                        "%(location)s, ",
                        _("group %(group_index)d ('%(group_id)d'): "
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
        validate_flow_group(ctx, "%s, group %d ('%s')"
                % (location, i+1, grp.id),
                grp)

    validate_markup(ctx, location, flow_desc.description)
    if hasattr(flow_desc.completion_text):
        validate_markup(ctx, location, flow_desc.completion_text)

# }}}


# {{{ calendar validation

def validate_calendar_desc_struct(ctx, location, events_desc):
    validate_struct(
            ctx,
            location,
            events_desc,
            required_attrs=[
                ],
            allowed_attrs=[
                ("event_kinds", Struct),
                ("events", Struct),
                ]
            )

    # FIXME could do more here

# }}}


def get_yaml_from_repo_safely(repo, full_name, commit_sha):
    from course.content import get_yaml_from_repo
    try:
        return get_yaml_from_repo(
                repo=repo, full_name=full_name, commit_sha=commit_sha,
                cached=False)
    except:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        raise ValidationError(
                "%(fullname)s: %(err_type)s: %(err_str)s" % {
                    'fullname': full_name,
                    "err_type": tp.__name__,
                    "err_str": unicode(e)})


def check_attributes_yml(vctx, repo, path, tree):
    try:
        _, attr_blob_sha = tree[".attributes.yml"]
    except KeyError:
        # no .attributes.yml here
        pass
    else:
        from relate.utils import dict_to_struct
        from yaml import load as load_yaml

        att_yml = dict_to_struct(load_yaml(repo[attr_blob_sha].data))

        loc = path + "/" + ".attributes.yml"
        validate_struct(
                vctx, loc, att_yml,
                required_attrs=[],
                allowed_attrs=[
                    ("public", list),
                ])

        if hasattr(att_yml, "public"):
            for i, l in enumerate(att_yml.public):
                if not isinstance(l, (str, unicode)):
                    raise ValidationError(
                            "%s: entry %d in 'public' is not a string"
                            % (loc, i+1))

    import stat
    for entry in tree.items():
        if stat.S_ISDIR(entry.mode):
            _, blob_sha = tree[entry.path]
            subtree = repo[blob_sha]
            check_attributes_yml(vctx, repo, path+"/"+entry.path, subtree)


def validate_course_content(repo, course_file, events_file,
        validate_sha, course=None):
    course_desc = get_yaml_from_repo_safely(repo, course_file,
            commit_sha=validate_sha)

    vctx = ValidationContext(
            repo=repo,
            commit_sha=validate_sha,
            course=course)

    validate_course_desc_struct(vctx, course_file, course_desc)

    try:
        from course.content import get_yaml_from_repo
        events_desc = get_yaml_from_repo(repo, events_file,
                commit_sha=validate_sha, cached=False)
    except ObjectDoesNotExist:
        # That's OK--no calendar info.
        pass
    else:
        validate_calendar_desc_struct(vctx, events_file, events_desc)

    check_attributes_yml(
            vctx, repo, "", get_repo_blob(repo, "", validate_sha))

    try:
        flows_tree = get_repo_blob(repo, "flows", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in flows_tree.items():
            if not entry.path.endswith(".yml"):
                continue

            from course.constants import FLOW_ID_REGEX
            flow_id = entry.path[:-4]
            match = re.match("^"+FLOW_ID_REGEX+"$", flow_id)
            if match is None:
                raise ValidationError(
                        string_concat("%s: ",
                            _("invalid flow name. "
                                "Flow names may only contain (roman) "
                                "letters, numbers, "
                                "dashes and underscores."))
                        % entry.path)

            location = "flows/%s" % entry.path
            flow_desc = get_yaml_from_repo_safely(repo, location,
                    commit_sha=validate_sha)

            validate_flow_desc(vctx, location, flow_desc)

    return vctx.warnings


# {{{ validation script support

class FileSystemFakeRepo(object):
    def __init__(self, root):
        self.root = root

    def controldir(self):
        return self.root

    def __getitem__(self, sha):
        return sha

    def __str__(self):
        return "<FAKEREPO:%s>" % self.root

    @property
    def tree(self):
        return FileSystemFakeRepoTree(self.root)


class FileSystemFakeRepoTreeEntry(object):
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode


class FileSystemFakeRepoTree(object):
    def __init__(self, root):
        self.root = root

    def __getitem__(self, name):
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


class FileSystemFakeRepoFile(object):
    def __init__(self, name):
        self.name = name

    @property
    def data(self):
        with open(self.name, "rb") as inf:
            return inf.read()


def validate_course_on_filesystem_script_entrypoint():
    from django.conf import settings
    settings.configure(DEBUG=True)

    import django
    django.setup()

    import os
    import argparse
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument("--course-file", default="course.yml")
    parser.add_argument("--events-file", default="events.yml")
    parser.add_argument('root', default=os.getcwd())

    args = parser.parse_args()

    fake_repo = FileSystemFakeRepo(args.root)
    warnings = validate_course_content(
            fake_repo,
            args.course_file, args.events_file,
            validate_sha=fake_repo, course=None)

    if warnings:
        print(_("WARNINGS: "))
        for w in warnings:
            print("***", w.location, w.text)

# }}}

# vim: foldmethod=marker
