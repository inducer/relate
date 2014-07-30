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
from django.utils.timezone import now

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from django.core.urlresolvers import reverse

from django.core.exceptions import ObjectDoesNotExist

from HTMLParser import HTMLParser


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

def _attr_to_string(key, val):
    if val is None:
        return key
    else:
        return "%s=\"%s\"" % (key, val)


class TagProcessingHTMLParser(HTMLParser):
    def __init__(self, out_file, process_tag_func):
        HTMLParser.__init__(self)

        self.out_file = out_file
        self.process_tag_func = process_tag_func

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<%s %s>" % (tag, " ".join(
            _attr_to_string(k, v) for k, v in attrs.iteritems())))

    def handle_endtag(self, tag):
        self.out_file.write("</%s>" % tag)

    def handle_startendtag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<%s %s/>" % (tag, " ".join(
            _attr_to_string(k, v) for k, v in attrs.iteritems())))

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
        raise NotImplementedError("I have no idea what a processing instruction is.")

    def unknown_decl(self, data):
        self.out_file.write("<![%s]>" % data)


class LinkFixerTreeprocessor(Treeprocessor):
    def __init__(self, md, course):
        Treeprocessor.__init__(self)
        self.md = md
        self.course = course

    def process_url(self, url):
        if url.startswith("flow:"):
            flow_id = url[5:]
            return reverse("course.flow.start_flow",
                        args=(self.course.identifier, flow_id))

        elif url.startswith("media:"):
            media_path = url[6:]
            return reverse("course.views.get_media",
                        args=(self.course.identifier, media_path))

        return None

    def process_tag(self, tag_name, attrs):
        changed_attrs = {}

        if tag_name == "a" and "href" in attrs:
            new_href = self.process_url(attrs["href"])

            if new_href is not None:
                changed_attrs["href"] = new_href

        elif tag_name == "img" and "src" in attrs:
            new_src = self.process_url(attrs["src"])

            if new_src is not None:
                changed_attrs["src"] = new_src

        return changed_attrs

    def process_etree_element(self, element):
        changed_attrs = self.process_tag(element.tag, element.attrib)

        for key, val in changed_attrs.iteritems():
            element.set(key, val)

    def walk_and_process_tree(self, root):
        self.process_etree_element(root)

        for child in root:
            self.walk_and_process_tree(child)

    def run(self, root):
        self.walk_and_process_tree(root)

        # root through and process Markdown's HTML stash (gross!)
        from cStringIO import StringIO

        for i, (html, safe) in enumerate(self.md.htmlStash.rawHtmlBlocks):
            outf = StringIO()
            parser = TagProcessingHTMLParser(outf, self.process_tag)
            parser.feed(html)

            self.md.htmlStash.rawHtmlBlocks[i] = (outf.getvalue(), safe)


class LinkFixerExtension(Extension):
    def __init__(self, course):
        self.course = course
        Extension.__init__(self)

    def extendMarkdown(self, md, md_globals):
        md.treeprocessors["courseflow_link_fixer"] = \
                LinkFixerTreeprocessor(md, self.course)


def markdown_to_html(course, text):
    import markdown
    return markdown.markdown(text,
        extensions=[
            LinkFixerExtension(course),
            "extra",
            ],
        output_format="html5")

# }}}


def get_course_repo_path(course):
    from os.path import join
    return join(settings.GIT_ROOT, course.identifier)


def get_course_repo(course):
    from dulwich.repo import Repo
    return Repo(get_course_repo_path(course))


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


DATE_RE = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
TRAILING_NUMERAL_RE = re.compile(r"^(.*)\s+([0-9]+)$")


class InvalidDatespec(ValueError):
    def __init__(self, datespec):
        ValueError.__init__(self, str(datespec))
        self.datespec = datespec


def parse_date_spec(course, datespec, return_now_on_error=True):
    if isinstance(datespec, datetime.datetime):
        return datespec
    if isinstance(datespec, datetime.date):
        return datetime.datetime(datespec)

    datespec = datespec.strip()

    match = DATE_RE.match(datespec)
    if match:
        return datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)))

    from course.models import TimeLabel

    match = TRAILING_NUMERAL_RE.match(datespec)
    if match:
        try:
            return TimeLabel.objects.get(
                    course=course,
                    kind=match.group(1),
                    ordinal=int(match.group(2))).time
        except ObjectDoesNotExist:
            if return_now_on_error:
                return now()
            else:
                raise InvalidDatespec(datespec)

    try:
        return TimeLabel.objects.get(
                course=course,
                kind=datespec,
                ordinal=None).time
    except ObjectDoesNotExist:
        if return_now_on_error:
            return now()
        else:
            raise InvalidDatespec(datespec)


def compute_chunk_weight_and_shown(course, chunk, role):
    from django.utils.timezone import now
    now_dt = now()

    for rule in chunk.rules:
        if hasattr(rule, "role"):
            if role != rule.role:
                continue
        if hasattr(rule, "start"):
            start_date = parse_date_spec(course, rule.start)
            if now_dt < start_date:
                continue
        if hasattr(rule, "end"):
            end_date = parse_date_spec(course, rule.end)
            if end_date < now_dt:
                continue

        shown = True
        if hasattr(rule, "shown"):
            shown = rule.shown

        return rule.weight, shown

    return 0


def get_course_desc(repo, course, commit_sha):
    return get_yaml_from_repo(repo, course.course_file, commit_sha)


def get_processed_course_chunks(course, course_desc, role):
    for chunk in course_desc.chunks:
        chunk.weight, chunk.shown = \
                compute_chunk_weight_and_shown(
                        course, chunk, role)
        chunk.html_content = markdown_to_html(course, chunk.content)

    course_desc.chunks.sort(key=lambda chunk: chunk.weight)

    return [mod for mod in course_desc.chunks
            if chunk.shown]


def get_flow_desc(repo, course, flow_id, commit_sha):
    flow = get_yaml_from_repo(repo, "flows/%s.yml" % flow_id, commit_sha)

    flow.description_html = markdown_to_html(
            course, getattr(flow, "description", None))
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

        components = stripped_typename.split(".")
        if len(components) != 2:
            raise ClassNotFoundError("repo page class must conist of two "
                    "dotted components (invalid: '%s')" % typename)

        module, classname = components
        module_name = "code/"+module+".py"
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


def set_up_flow_session_page_data(repo, flow_session, flow, commit_sha):
    from course.models import FlowPageData

    data = None

    ordinal = 0
    for grp in flow.groups:
        for page_desc in grp.pages:
            data = FlowPageData()
            data.flow_session = flow_session
            data.ordinal = ordinal
            data.is_last = False
            data.group_id = grp.id
            data.page_id = page_desc.id

            page = instantiate_flow_page(
                    "course '%s', flow '%s', page '%s/%s'"
                    % (flow_session.participation.course, flow_session.flow_id,
                        grp.id, page_desc.id),
                    repo, page_desc, commit_sha)
            data.data = page.make_page_data()
            data.save()

            ordinal += 1

    return ordinal


# vim: foldmethod=marker
