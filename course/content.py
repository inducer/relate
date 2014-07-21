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

from django.conf import settings

import re
import datetime

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from django.core.urlresolvers import reverse

from django.core.exceptions import ObjectDoesNotExist


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
        raise ObjectDoesNotExist("resource '%s' not found" % full_name)


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


def get_flow_desc(repo, course, flow_id, commit_sha):
    flow = get_yaml_from_repo(repo, "flows/%s.yml" % flow_id, commit_sha)

    flow.description_html = html_body(course, getattr(flow, "description", None))
    return flow


def get_flow_page_desc(flow_id, flow, group_id, page_id):
    for grp in flow.groups:
        if grp.id == group_id:
            for page in grp.pages:
                if page.id == page_id:
                    return page

    raise ObjectDoesNotExist("page '%s/%s' in flow '%s'"
            % (group_id, page_id, flow_id))


class ClassNotFoundError(RuntimeError):
    pass


def import_class(name):
    components = name.split('.')

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


def get_flow_page_class(repo, typename, commit_sha):
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

    if typename.startswith("repo:"):
        stripped_typename = typename[5:]

        components = stripped_typename.split(",")
        if len(components) != 2:
            raise ClassNotFoundError("repo page class must conist of two "
                    "dotted components (invalid: '%s')" % typename)

        module, classname = components
        from os.path import join
        module_name = join("code", module+".py")
        module_code = get_repo_blob(repo, module_name, commit_sha).data

        module_dict = {}

        exec(compile(module_code, module_name, 'exec'), module_dict)

        try:
            return module_dict[classname]
        except AttributeError:
            raise ClassNotFoundError(typename)
    else:
        raise ClassNotFoundError(typename)


def instantiate_flow_page(location, repo, page_desc, commit_sha):
    class_ = get_flow_page_class(repo, page_desc.type, commit_sha)
    return class_(location, page_desc)


def set_up_flow_visit_page_data(repo, flow_visit, flow, commit_sha):
    from course.models import FlowPageData

    data = None

    ordinal = 0
    for grp in flow.groups:
        for page_desc in grp.pages:
            data = FlowPageData()
            data.flow_visit = flow_visit
            data.ordinal = ordinal
            data.is_last = False
            data.group_id = grp.id
            data.page_id = page_desc.id

            page = instantiate_flow_page(
                    "course '%s', flow '%s', page '%s/%s'"
                    % (flow_visit.participation.course, flow_visit.flow_id,
                        grp.id, page_desc.id),
                    repo, page_desc, commit_sha)
            data.data = page.make_page_data()
            data.save()

            ordinal += 1

    return ordinal



# vim: foldmethod=marker
