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
from django.core.urlresolvers import reverse
from django.core.exceptions import ObjectDoesNotExist
import django.core.cache as cache

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from HTMLParser import HTMLParser

from jinja2 import BaseLoader as BaseTemplateLoader, TemplateNotFound


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


# {{{ repo interaction

def get_course_repo_path(course):
    from os.path import join
    return join(settings.GIT_ROOT, course.identifier)


COURSE_REPOS = {}


def get_course_repo(course):
    try:
        return COURSE_REPOS[course.pk]
    except KeyError:
        from dulwich.repo import Repo
        repo = Repo(get_course_repo_path(course))

        COURSE_REPOS[course.pk] = repo

        return repo


def get_repo_blob(repo, full_name, commit_sha):
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


def get_repo_blob_data_cached(repo, full_name, commit_sha):
    cache_key = "%%%1".join((repo.controldir(), full_name, commit_sha))

    def_cache = cache.caches["default"]
    result = def_cache.get(cache_key)
    if result is not None:
        return result

    result = get_repo_blob(repo, full_name, commit_sha).data

    def_cache.add(cache_key, result, None)
    return result


def get_yaml_from_repo(repo, full_name, commit_sha):
    cache_key = "%%%2".join((repo.controldir(), full_name, commit_sha))

    def_cache = cache.caches["default"]
    result = def_cache.get(cache_key)
    if result is not None:
        return result

    from yaml import load
    result = dict_to_struct(
            load(get_repo_blob(repo, full_name, commit_sha).data))

    def_cache.add(cache_key, result, None)

    return result

# }}}


# {{{ markup

def _attr_to_string(key, val):
    if val is None:
        return key
    elif "\"" in val:
        return "%s='%s'" % (key, val)
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
    def __init__(self, md, course, commit_sha):
        Treeprocessor.__init__(self)
        self.md = md
        self.course = course
        self.commit_sha = commit_sha

    def get_course_identifier(self):
        if self.course is None:
            return "bogus-course-identifier"
        else:
            return self.course.identifier

    def process_url(self, url):
        if url.startswith("flow:"):
            flow_id = url[5:]
            return reverse("course.flow.start_flow",
                        args=(self.get_course_identifier(), flow_id))

        elif url.startswith("media:"):
            media_path = url[6:]
            return reverse("course.views.get_media",
                        args=(
                            self.get_course_identifier(),
                            self.commit_sha,
                            media_path))

        return None

    def process_tag(self, tag_name, attrs):
        changed_attrs = {}

        if tag_name == "table":
            changed_attrs["class"] = "table table-condensed"

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
        from StringIO import StringIO

        for i, (html, safe) in enumerate(self.md.htmlStash.rawHtmlBlocks):
            outf = StringIO()
            parser = TagProcessingHTMLParser(outf, self.process_tag)
            parser.feed(html)

            self.md.htmlStash.rawHtmlBlocks[i] = (outf.getvalue(), safe)


class LinkFixerExtension(Extension):
    def __init__(self, course, commit_sha):
        Extension.__init__(self)
        self.course = course
        self.commit_sha = commit_sha

    def extendMarkdown(self, md, md_globals):
        md.treeprocessors["courseflow_link_fixer"] = \
                LinkFixerTreeprocessor(md, self.course, self.commit_sha)


class GitTemplateLoader(BaseTemplateLoader):
    def __init__(self, repo, commit_sha):
        self.repo = repo
        self.commit_sha = commit_sha

    def get_source(self, environment, template):
        try:
            data = get_repo_blob(self.repo, template, self.commit_sha).data
        except ObjectDoesNotExist:
            raise TemplateNotFound(template)

        source = data.decode('utf-8')

        def is_up_to_date():
            # There's not much point to caching here, because we create
            # a new loader for every request anyhow...
            return False

        return source, None, lambda: False


def remove_prefix(prefix, s):
    if s.startswith(prefix):
        return s[len(prefix):]
    else:
        return s


JINJA_PREFIX = "[JINJA]"


def markup_to_html(course, repo, commit_sha, text):
    if text.lstrip().startswith(JINJA_PREFIX):
        text = remove_prefix(JINJA_PREFIX, text.lstrip())

        from jinja2 import Environment
        env = Environment(loader=GitTemplateLoader(repo, commit_sha))
        template = env.from_string(text)
        text = template.render()

    import markdown
    return markdown.markdown(text,
        extensions=[
            LinkFixerExtension(course, commit_sha),
            "extra",
            ],
        output_format="html5")

# }}}


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


def compute_chunk_weight_and_shown(course, chunk, role, now_datetime):
    for rule in chunk.rules:
        if hasattr(rule, "role"):
            if role != rule.role:
                continue
        if hasattr(rule, "start"):
            start_date = parse_date_spec(course, rule.start)
            if now_datetime < start_date:
                continue
        if hasattr(rule, "end"):
            end_date = parse_date_spec(course, rule.end)
            if end_date < now_datetime:
                continue

        shown = True
        if hasattr(rule, "shown"):
            shown = rule.shown

        return rule.weight, shown

    return 0


def get_course_desc(repo, course, commit_sha):
    return get_yaml_from_repo(repo, course.course_file, commit_sha)


def get_processed_course_chunks(course, repo, commit_sha,
        course_desc, role, now_datetime):
    for chunk in course_desc.chunks:
        chunk.weight, chunk.shown = \
                compute_chunk_weight_and_shown(
                        course, chunk, role, now_datetime)
        chunk.html_content = markup_to_html(course, repo, commit_sha, chunk.content)

    course_desc.chunks.sort(key=lambda chunk: chunk.weight, reverse=True)

    return [mod for mod in course_desc.chunks
            if chunk.shown]


def get_flow_desc(repo, course, flow_id, commit_sha):
    flow = get_yaml_from_repo(repo, "flows/%s.yml" % flow_id, commit_sha)

    flow.description_html = markup_to_html(
            course, repo, commit_sha, getattr(flow, "description", None))
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

    from course.validation import ValidationContext
    vctx = ValidationContext(
            repo=repo, commit_sha=commit_sha)

    return class_(vctx, location, page_desc)


def set_up_flow_session_page_data(repo, flow_session,
        course_identifier, flow_desc, commit_sha):
    from course.models import FlowPageData

    data = None

    ordinal = 0
    for grp in flow_desc.groups:
        for page_desc in grp.pages:
            data = FlowPageData()
            data.flow_session = flow_session
            data.ordinal = ordinal
            data.is_last = False
            data.group_id = grp.id
            data.page_id = page_desc.id

            page = instantiate_flow_page(
                    "course '%s', flow '%s', page '%s/%s'"
                    % (course_identifier, flow_session.flow_id,
                        grp.id, page_desc.id),
                    repo, page_desc, commit_sha)
            data.data = page.make_page_data()
            data.save()

            ordinal += 1

    return ordinal


def get_active_commit_sha(course, participation):
    sha = course.active_git_commit_sha

    if participation is not None and participation.preview_git_commit_sha:
        sha = participation.preview_git_commit_sha

    return sha.encode()


# vim: foldmethod=marker
