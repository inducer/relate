from django.conf import settings

import re
import datetime
import six

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from django.core.urlresolvers import reverse

from django.http import Http404

# {{{ tools

class Struct(object):
    def __init__(self, entries):
        for name, val in entries.iteritems():
            self.__dict__[name] = dict_to_struct(val)

    def __repr__(self):
        return repr(self.__dict__)


def dict_to_struct(data):
    if isinstance(data, list):
        return [dict_to_struct(d) for d in data]
    elif isinstance(data, dict):
        return Struct(data)
    else:
        return data

# }}}


# {{{ formatting

class LinkFixerTreeprocessor(Treeprocessor):
    def __init__(self, course):
        Treeprocessor.__init__(self)
        self.course = course

    def run(self, root):
        if root.tag == "a" and root.attrib["href"].startswith("flow:"):
            flow_id = root.attrib["href"][5:]
            root.set("href",
                    reverse("course.views.start_flow",
                        args=(self.course.identifier, flow_id)))

        for child in root:
            self.run(child)


class LinkFixerExtension(Extension):
    def __init__(self, course):
        self.course = course
        Extension.__init__(self)

    def extendMarkdown(self, md, md_globals):
        md.treeprocessors["courseflow_link_fixer"] = \
                LinkFixerTreeprocessor(self.course)


def html_body(course, text):
    import markdown
    return markdown.markdown(text,
        extensions=[
            LinkFixerExtension(course)
            ])

# }}}


def get_course_repo(course):
    from os.path import join

    from dulwich.repo import Repo
    return Repo(join(settings.GIT_ROOT, course.identifier))


def get_repo_blob(repo, full_name, commit_sha=None):
    names = full_name.split("/")

    tree_sha = repo[commit_sha].tree
    tree = repo[tree_sha]

    try:
        for name in names[:-1]:
            mode, blob_sha = tree[name.encode()]
            tree = repo[blob_sha]

        mode, blob_sha = tree[names[-1].encode()]
        return repo[blob_sha]
    except KeyError:
        # TODO: Proper 404
        raise Http404("resource '%s' not found" % full_name)


def get_yaml_from_repo(repo, full_name, commit_sha):
    from yaml import load
    return dict_to_struct(
            load(get_repo_blob(repo, full_name, commit_sha).data))


DATE_RE_MATCH = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
WEEK_RE_MATCH = re.compile(r"^(start|end)\s+week\s+([0-9]+)$")


def parse_absolute_date_spec(date_spec):
    match = DATE_RE_MATCH.match(date_spec)
    if not match:
        raise ValueError("invalid absolute datespec: %s" % date_spec)

    return datetime.date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)))


def parse_date_spec(course_desc, date_spec):
    match = DATE_RE_MATCH.match(date_spec)
    if match:
        return datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)))

    match = WEEK_RE_MATCH.match(date_spec)
    if match:
        n = int(match.group(2)) - 1
        if match.group(1) == "start":
            return course_desc.first_course_week_start + datetime.timedelta(days=n*7)
        elif match.group(1) == "end":
            return (course_desc.first_course_week_start
                    + datetime.timedelta(days=n*7+6))
        else:
            raise ValueError("invalid datespec: %s" % date_spec)

    raise ValueError("invalid datespec: %s" % date_spec)


def compute_chunk_weight_and_shown(course_desc, chunk, role):
    now = datetime.datetime.now().date()

    for rule in chunk.rules:
        if hasattr(rule, "role"):
            if role != rule.role:
                continue
        if hasattr(rule, "start"):
            start_date = parse_date_spec(course_desc, rule.start)
            if now < start_date:
                continue
        if hasattr(rule, "end"):
            end_date = parse_date_spec(course_desc, rule.end)
            if end_date < now:
                continue

        shown = True
        if hasattr(rule, "shown"):
            shown = rule.shown

        return rule.weight, shown

    return 0


class NoCourseContent(RuntimeError):
    pass


def get_course_desc(repo, commit_sha):
    course_desc = get_yaml_from_repo(repo, "course.yml", commit_sha)

    assert isinstance(course_desc.course_start, datetime.date)
    assert isinstance(course_desc.course_end, datetime.date)

    # a Monday
    course_desc.first_course_week_start = \
            course_desc.course_start - datetime.timedelta(
                    days=course_desc.course_start.weekday())

    return course_desc


def get_processed_course_chunks(course, course_desc, role):
    for chunk in course_desc.chunks:
        chunk.weight, chunk.shown = \
                compute_chunk_weight_and_shown(
                        course_desc, chunk, role)
        chunk.html_content = html_body(course, chunk.content)

    course_desc.chunks.sort(key=lambda chunk: chunk.weight)

    return [mod for mod in course_desc.chunks
            if chunk.shown]


def get_flow(course, flow_id, commit_sha):
    flow = get_course_file_yaml(course, "flows/%s.yml")

    flow.description_html = html_body(course, getattr(flow, "description", None))
    return flow


# {{{ validation

class ValidationError(RuntimeError):
    pass


ID_RE = re.compile(r"^[\w]+$")


def validate_identifier(location, s):
    if not ID_RE.match(s):
        raise ValidationError("%s: invalid identifier '%s'"
                % (location, s))


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

                if not isinstance(val, allowed_types):
                    raise ValidationError("%s: attribute '%s' has "
                            "wrong type: got '%s', expected '%s'"
                            % (location, attr, type(val).__name__,
                            allowed_types))

    if present_attrs:
        raise ValidationError("%s: extraneous attribute(s) '%s'"
                % (location, ",".join(present_attrs)))


datespec_types = (datetime.date, six.string_types)


def validate_chunk_rule(chunk_rule):
    validate_struct(
            "chunk_rule",
            chunk_rule,
            required_attrs=[
                ("weight", int),
                ],
            allowed_attrs=[
                ("start", (str, datetime.date)),
                ("end", (str, datetime.date)),
                ("role", str),
                ("shown", bool),
            ])


def validate_chunk(chunk):
    validate_struct(
            "chunk",
            chunk,
            required_attrs=[
                ("title", str),
                ("id", str),
                ("rules", list),
                ("content", str),
                ],
            allowed_attrs=[]
            )

    for rule in chunk.rules:
        validate_chunk_rule(rule)


def validate_course_desc_struct(course_desc):
    validate_struct(
            "course_desc",
            course_desc,
            required_attrs=[
                ("name", str),
                ("number", str),
                ("run", str),
                ("description", str),
                ("course_start", datetime.date),
                ("course_end", datetime.date),
                ("chunks", list),
                ],
            allowed_attrs=[]
            )

    for chunk in course_desc.chunks:
        validate_chunk(chunk)


# {{{ flow validation

def validate_flow_page(location, page):
    validate_struct(
            location,
            page,
            required_attrs=[
                ("type", str),
                ("id", str),
                ],
            allowed_attrs=[
                ("content", str),
                ("prompt", str),
                ("title", str),
                ("answers", list),
                ("choices", list),
                ("value", (int, float)),
                ]
            )

    validate_identifier(location, page.id)


def validate_flow_group(location, grp):
    validate_struct(
            location,
            grp,
            required_attrs=[
                ("id", str),
                ("pages", list),
                ],
            allowed_attrs=[]
            )

    for i, page in enumerate(grp.pages):
        validate_flow_page("%s, page %d" % (location, i+1), page)

    validate_identifier(location, grp.id)

    # {{{ check page id uniqueness

    page_ids = set()

    for page in grp.pages:
        if page.id in page_ids:
            raise ValidationError("%s: page id '%s' not unique"
                    % (location, page.id))

        page_ids.add(page.id)

    # }}}


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


def validate_flow_permission(location, permission):
    from course.models import flow_permission
    if permission not in [
            flow_permission.view_past,
            flow_permission.start_credit,
            flow_permission.start_no_credit,
            ]:
        raise ValidationError("%s: invalid flow permission"
                % location)


def validate_flow_access_rule(location, rule):
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
                ("time_limit", str),
                ("allowed_visit_count", int),
                ]
            )

    for i, perm in enumerate(rule.permissions):
        validate_flow_permission(
                "%s, permission %d" % (location, i+1),
                perm)

    if hasattr(rule, "roles"):
        for i, role in enumerate(rule.roles):
            validate_role(
                    "%s, role %d" % (location, i+1),
                    role)

    # TODO: validate time limit


def validate_flow_desc(location, flow_desc):
    validate_struct(
            location,
            flow_desc,
            required_attrs=[
                ("title", str),
                ("description", str),
                ("flow_groups", list),
                ],
            allowed_attrs=[
                ("access_rules", list),
                ]
            )

    if hasattr(flow_desc, "access_rules"):
        for i, rule in enumerate(flow_desc.access_rules):
            validate_flow_access_rule(
                    "%s, access rule %d" % (location, i+1),
                    rule)

        last_rule = flow_desc.access_rules[-1]
        if (
                hasattr(last_rule, "roles")
                or hasattr(last_rule, "start")
                or hasattr(last_rule, "end")
                ):
            raise ValidationError("%s: last access rule must set default access "
                    "(i.e. have no attributes other than 'permissions')"
                    % location)

    # {{{ check group id uniqueness

    group_ids = set()

    for grp in flow_desc.flow_groups:
        if grp.id in group_ids:
            raise ValidationError("%s: group id '%s' not unique"
                    % (location, grp.id))

        group_ids.add(grp.id)

    # }}}

    for i, grp in enumerate(flow_desc.flow_groups):
        validate_flow_group("%s, group %d ('%s')" % (location, i+1, grp.id), grp)

# }}}


def validate_course_content(repo, validate_sha):
    course_desc = get_yaml_from_repo(repo, "course.yml",
            commit_sha=validate_sha)

    validate_course_desc_struct(course_desc)

    flows_tree = get_repo_blob(repo, "flows", validate_sha)

    for entry in flows_tree.items():
        location = "flows/%s" % entry.path
        flow_desc = get_yaml_from_repo(repo, location,
                commit_sha=validate_sha)

        validate_flow_desc(location, flow_desc)

# }}}

# vim: foldmethod=marker
