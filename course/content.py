from django.conf import settings

import re
import datetime

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from django.core.urlresolvers import reverse


# {{{ tools

class Struct:
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


def get_git_repo(course):
    from os.path import join

    from gittle import Gittle
    return Gittle(join(settings.GIT_ROOT, course.identifier))


def get_course_file(request, course, full_name, commit_sha=None):
    repo = get_git_repo(course)

    if commit_sha is None:
        commit_sha = course.active_git_commit_sha

    if isinstance(commit_sha, unicode):
        commit_sha = commit_sha.encode()

    names = full_name.split("/")

    tree_sha = repo[commit_sha].tree
    tree = repo[tree_sha]

    try:
        for name in names[:-1]:
            mode, blob_sha = tree[name.encode()]
            assert mode == repo.MODE_DIRECTORY
            tree = repo[blob_sha]

        mode, blob_sha = tree[names[-1].encode()]
        return repo[blob_sha].data
    except KeyError:
        # TODO: Proper 404
        raise RuntimeError("resource '%s' not found" % full_name)


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


def compute_module_weight(course_desc, module):
    now = datetime.datetime.now().date()

    for wspec in module.weight:
        if hasattr(wspec, "start"):
            start_date = parse_date_spec(course_desc, wspec.start)
            if now < start_date:
                continue
        if hasattr(wspec, "end"):
            end_date = parse_date_spec(course_desc, wspec.end)
            if end_date < now:
                continue
        return wspec.value

    return 0


def get_course_desc(request, course):
    from yaml import load
    course_desc = dict_to_struct(
            load(get_course_file(request, course, "course.yml")))

    assert isinstance(course_desc.course_start, datetime.date)
    assert isinstance(course_desc.course_end, datetime.date)

    # a Monday
    course_desc.first_course_week_start = \
            course_desc.course_start - datetime.timedelta(
                    days=course_desc.course_start.weekday())

    for module in course_desc.modules:
        module.weight = compute_module_weight(course_desc, module)
        module.html_content = html_body(course, module.content)

    course_desc.modules.sort(key=lambda module: module.weight)

    course_desc.modules = [mod for mod in course_desc.modules if mod.weight >= 0]

    return course_desc


def get_flow(request, course, flow_id, commit_sha):
    from yaml import load
    flow = dict_to_struct(load(get_course_file(request, course,
        "flows/%s.yml" % flow_id)))

    flow.description_html = html_body(course, getattr(flow, "description", None))
    return flow


# {{{ validation

def validate_course_content(course, validate_sha):
    #raise RuntimeError("not valid")
    pass


# }}}
