# -*- coding: utf-8 -*-

from __future__ import division

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

from course.content import get_yaml_from_repo, get_repo_blob

from django.core.exceptions import ObjectDoesNotExist


# {{{ validation tools

class ValidationError(RuntimeError):
    pass


ID_RE = re.compile(r"^[\w]+$")


def validate_identifier(location, s):
    if not ID_RE.match(s):
        raise ValidationError("%s: invalid identifier '%s'"
                % (location, s))


def validate_role(location, role):
    from course.models import participation_role

    if role not in [
            participation_role.instructor,
            participation_role.teaching_assistant,
            participation_role.student,
            participation_role.unenrolled,
            ]:
        raise ValidationError("%s: invalid role '%s'"
                % (location, role))


def validate_struct(location, obj, required_attrs, allowed_attrs):
    """
    :arg required_attrs: an attribute validation list (see below)
    :arg allowed_attrs: an attribute validation list (see below)

    An attribute validation list is a list of elements, where each element is
    either a string (the name of the attribute), in which case the type of each
    attribute is not checked, or a tuple *(name, type)*, where type is valid
    as a second argument to :func:`isinstance`.
    """

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
                    raise ValidationError("%s: attribute '%s' missing"
                            % (location, attr))
            else:
                present_attrs.remove(attr)
                val = getattr(obj, attr)

                if allowed_types == str:
                    # Love you, too, Python 2.
                    allowed_types = (str, unicode)

                if not isinstance(val, allowed_types):
                    raise ValidationError("%s: attribute '%s' has "
                            "wrong type: got '%s', expected '%s'"
                            % (location, attr, type(val).__name__,
                            allowed_types))

    if present_attrs:
        raise ValidationError("%s: extraneous attribute(s) '%s'"
                % (location, ",".join(present_attrs)))


datespec_types = (datetime.date, six.string_types)

# }}}


class ValidationWarning(object):
    def __init__(self, location, text):
        self.location = location
        self.text = text


class ValidationContext(object):
    """
    .. attribute:: repo
    .. attribute:: commit_sha
    .. attribute:: datespec_callback

        a function that is supposed to be called on all encountered datespecs
    """

    def __init__(self, repo, commit_sha, datespec_callback=None):
        self.repo = repo
        self.commit_sha = commit_sha
        self.datespec_callback = datespec_callback
        self.warnings = []

    def encounter_datespec(self, datespec):
        if self.datespec_callback is not None:
            self.datespec_callback(datespec)

    def add_warning(self, *args, **kwargs):
        self.warnings.append(ValidationWarning(*args, **kwargs))


# {{{ course page validation

def validate_markup(ctx, location, markup_str):
    from course.content import markup_to_html
    try:
        markup_to_html(
                course=None,
                repo=ctx.repo,
                commit_sha=ctx.commit_sha,
                text=markup_str)
    except:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        raise ValidationError("%s: %s: %s" % (
            location, tp.__name__, str(e)))


def validate_chunk_rule(ctx, location, chunk_rule):
    validate_struct(
            location,
            chunk_rule,
            required_attrs=[
                ("weight", int),
                ],
            allowed_attrs=[
                ("start", (str, datetime.date)),
                ("end", (str, datetime.date)),
                ("role", str),
                ("roles", list),
                ("shown", bool),
            ])

    if hasattr(chunk_rule, "start"):
        ctx.encounter_datespec(chunk_rule.start)

    if hasattr(chunk_rule, "end"):
        ctx.encounter_datespec(chunk_rule.end)

    if hasattr(chunk_rule, "role"):
        ctx.add_warning(location, "Uses deprecated 'role' attribute--"
                "use 'roles' instead")

        validate_role(location, chunk_rule.role)

    if hasattr(chunk_rule, "roles"):
        for role in chunk_rule.roles:
            validate_role(location, role)


def validate_chunk(ctx, location, chunk):
    validate_struct(
            location,
            chunk,
            required_attrs=[
                ("title", str),
                ("id", str),
                ("rules", list),
                ("content", str),
                ],
            allowed_attrs=[]
            )

    for i, rule in enumerate(chunk.rules):
        validate_chunk_rule(ctx,
                "%s, rule %d" % (location, i+1),
                rule)

    validate_markup(ctx, location, chunk.content)


def validate_course_desc_struct(ctx, location, course_desc):
    validate_struct(
            location,
            course_desc,
            required_attrs=[
                ("name", str),
                ("number", str),
                ("run", str),
                ("chunks", list),
                ],
            allowed_attrs=[]
            )

    for i, chunk in enumerate(course_desc.chunks):
        validate_chunk(ctx,
                "%s, chunk %d ('%s')" % (location, i+1, chunk.id),
                chunk)

    # {{{ check chunk id uniqueness

    chunk_ids = set()

    for chunk in course_desc.chunks:
        if chunk.id in chunk_ids:
            raise ValidationError("%s: chunk id '%s' not unique"
                    % (location, chunk.id))

        chunk_ids.add(chunk.id)

    # }}}

# }}}


# {{{ flow validation

def validate_flow_page(ctx, location, page_desc):
    validate_identifier(location, page_desc.id)

    from course.content import get_flow_page_class
    try:
        class_ = get_flow_page_class(ctx.repo, page_desc.type, ctx.commit_sha)
        class_(ctx, location, page_desc)
    except ValidationError:
        raise
    except:
        tp, e, _ = sys.exc_info()

        from traceback import format_exc
        raise ValidationError(
                "%s: could not instantiate flow page: %s: %s<br><pre>%s</pre>"
                % (location, tp.__name__, str(e), format_exc()))


def validate_flow_group(ctx, location, grp):
    validate_struct(
            location,
            grp,
            required_attrs=[
                ("id", str),
                ("pages", list),
                ],
            allowed_attrs=[]
            )

    for i, page_desc in enumerate(grp.pages):
        validate_flow_page(
                ctx,
                "%s, page %d ('%s')" % (location, i+1, page_desc.id),
                page_desc)

    validate_identifier(location, grp.id)

    # {{{ check page id uniqueness

    page_ids = set()

    for page_desc in grp.pages:
        if page_desc.id in page_ids:
            raise ValidationError("%s: page id '%s' not unique"
                    % (location, page_desc.id))

        page_ids.add(page_desc.id)

    # }}}


def validate_flow_permission(ctx, location, permission):
    from course.models import FLOW_PERMISSION_CHOICES
    if permission not in dict(FLOW_PERMISSION_CHOICES):
        raise ValidationError("%s: invalid flow permission '%s'"
                % (location, permission))


def validate_flow_access_rule(ctx, location, rule):
    validate_struct(
            location,
            rule,
            required_attrs=[
                ("permissions", list),
                ],
            allowed_attrs=[
                ("roles", list),
                ("start", (datetime.date, str)),
                ("end", (datetime.date, str)),
                ("credit_percent", (int, float)),
                # ("time_limit", str),
                ("allowed_session_count", int),
                ]
            )

    for i, perm in enumerate(rule.permissions):
        validate_flow_permission(
                ctx,
                "%s, permission %d" % (location, i+1),
                perm)

    if hasattr(rule, "roles"):
        for i, role in enumerate(rule.roles):
            validate_role(
                    "%s, role %d" % (location, i+1),
                    role)

    if hasattr(rule, "start"):
        ctx.encounter_datespec(rule.start)

    if hasattr(rule, "end"):
        ctx.encounter_datespec(rule.end)


def validate_flow_desc(ctx, location, flow_desc):
    validate_struct(
            location,
            flow_desc,
            required_attrs=[
                ("title", str),
                ("description", str),
                ("groups", list),
                ("completion_text", str),
                ],
            allowed_attrs=[
                ("access_rules", list),
                ("grade_aggregation_strategy", str),
                ]
            )

    encountered_permissions = set()

    if hasattr(flow_desc, "access_rules"):
        for i, rule in enumerate(flow_desc.access_rules):
            validate_flow_access_rule(ctx,
                    "%s, access rule %d" % (location, i+1),
                    rule)

            encountered_permissions.update(rule.permissions)

        last_rule = flow_desc.access_rules[-1]
        if (
                hasattr(last_rule, "roles")
                or hasattr(last_rule, "start")
                or hasattr(last_rule, "end")
                ):
            raise ValidationError("%s: last access rule must set default access "
                    "(i.e. have no attributes other than 'permissions')"
                    % location)

    if hasattr(flow_desc, "grade_aggregation_strategy"):
        from course.models import GRADE_AGGREGATION_STRATEGY_CHOICES
        if flow_desc.grade_aggregation_strategy not in \
                dict(GRADE_AGGREGATION_STRATEGY_CHOICES):
            raise ValidationError("%s: invalid grade aggregation strategy"
                    % location)
    else:
        from course.models import flow_permission
        if flow_permission.start_credit in encountered_permissions:
            raise ValidationError(
                    "%s: flow which can be used for credit must have "
                    "grade_aggregation_strategy"
                    % location)

    # {{{ check for non-emptiness

    flow_has_page = False
    for i, grp in enumerate(flow_desc.groups):
        group_has_page = False

        for page in grp.pages:
            group_has_page = flow_has_page = True
            break

        if not group_has_page:
            raise ValidationError("%s, group %d ('%d'): no pages found"
                    % (location, i+1, grp.id))

    if not flow_has_page:
        raise ValidationError("%s: no pages found"
                % location)

    # }}}

    # {{{ check group id uniqueness

    group_ids = set()

    for grp in flow_desc.groups:
        if grp.id in group_ids:
            raise ValidationError("%s: group id '%s' not unique"
                    % (location, grp.id))

        group_ids.add(grp.id)

    # }}}

    for i, grp in enumerate(flow_desc.groups):
        validate_flow_group(ctx, "%s, group %d ('%s')"
                % (location, i+1, grp.id),
                grp)

    validate_markup(ctx, location, flow_desc.description)
    validate_markup(ctx, location, flow_desc.completion_text)

# }}}


def validate_course_content(repo, course_file, validate_sha, datespec_callback=None):
    try:
        course_desc = get_yaml_from_repo(repo, course_file,
                commit_sha=validate_sha)
    except:
        from traceback import print_exc
        print_exc()

        tp, e, _ = sys.exc_info()

        raise ValidationError("%s: %s: %s" % (
            course_file, tp.__name__, str(e)))

    ctx = ValidationContext(
            repo=repo,
            commit_sha=validate_sha,
            datespec_callback=datespec_callback)

    validate_course_desc_struct(ctx, course_file, course_desc)

    try:
        flows_tree = get_repo_blob(repo, "flows", validate_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in flows_tree.items():
            location = "flows/%s" % entry.path
            flow_desc = get_yaml_from_repo(repo, location,
                    commit_sha=validate_sha)

            validate_flow_desc(ctx, location, flow_desc)

    return ctx.warnings

# }}}

# vim: foldmethod=marker
