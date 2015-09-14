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
from django.utils.translation import ugettext as _

import re
import datetime
import six

from django.utils.timezone import now
from django.core.exceptions import ObjectDoesNotExist, ImproperlyConfigured

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from six.moves import html_parser

from jinja2 import BaseLoader as BaseTemplateLoader, TemplateNotFound

from relate.utils import dict_to_struct

from yaml import load as load_yaml


# {{{ repo interaction

class SubdirRepoWrapper(object):
    def __init__(self, repo, subdir):
        self.repo = repo

        # This wrapper should only get used if there is a subdir to be had.
        assert subdir
        self.subdir = subdir

    def controldir(self):
        return self.repo.controldir()


def get_course_repo_path(course):
    from os.path import join
    return join(settings.GIT_ROOT, course.identifier)


def get_course_repo(course):
    from dulwich.repo import Repo
    repo = Repo(get_course_repo_path(course))

    if course.course_root_path:
        return SubdirRepoWrapper(repo, course.course_root_path)
    else:
        return repo


def get_repo_blob(repo, full_name, commit_sha):
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(repo, SubdirRepoWrapper):
        # full_name must be non-empty
        full_name = repo.subdir + "/" + full_name
        repo = repo.repo

    names = full_name.split("/")

    # Allow non-ASCII file name
    full_name = full_name.encode('utf-8')

    tree_sha = repo[commit_sha].tree
    tree = repo[tree_sha]

    if not full_name:
        return tree

    try:
        for name in names[:-1]:
            if not name:
                # tolerate empty path components (begrudgingly)
                continue

            mode, blob_sha = tree[name.encode()]
            tree = repo[blob_sha]

        mode, blob_sha = tree[names[-1].encode()]
        return repo[blob_sha]
    except KeyError:
        raise ObjectDoesNotExist(_("resource '%s' not found") % full_name)


def get_repo_blob_data_cached(repo, full_name, commit_sha):
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(commit_sha, six.binary_type):
        from six.moves.urllib.parse import quote_plus
        cache_key = "%%%1".join((
            quote_plus(repo.controldir()),
            quote_plus(full_name),
            commit_sha.decode()))
    else:
        cache_key = None

    try:
        import django.core.cache as cache
    except ImproperlyConfigured:
        cache_key = None

    if cache_key is None:
        return get_repo_blob(repo, full_name, commit_sha).data

    def_cache = cache.caches["default"]

    result = None
    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        result = def_cache.get(cache_key)
    if result is not None:
        return result

    result = get_repo_blob(repo, full_name, commit_sha).data

    if len(result) <= getattr(settings, "RELATE_CACHE_MAX_BYTES", 0):
        def_cache.add(cache_key, result, None)

    return result


JINJA_YAML_RE = re.compile(
    r"^\[JINJA\]\s*$(.*?)^\[\/JINJA\]\s*$",
    re.MULTILINE | re.DOTALL)
YAML_BLOCK_START_SCALAR_RE = re.compile(
    r":\s*[|>](?:[0-9][-+]?|[-+][0-9]?)?(?:\s*\#.*)?$")
GROUP_COMMENT_START = re.compile(r"^\s*#\s*\{\{\{")
LEADING_SPACES_RE = re.compile(r"^( *)")


def expand_yaml_macros(repo, commit_sha, yaml_str):
    if isinstance(yaml_str, six.binary_type):
        yaml_str = yaml_str.decode("utf-8")

    from jinja2 import Environment, StrictUndefined
    jinja_env = Environment(
            loader=GitTemplateLoader(repo, commit_sha),
            undefined=StrictUndefined)

    def compute_replacement(match):
        template = jinja_env.from_string(match.group(1))
        return template.render()

    yaml_str, count = JINJA_YAML_RE.subn(compute_replacement, yaml_str)

    if count:
        # The file uses explicit YAML tags. Assume that it doesn't
        # want anything else processed through YAML.
        return yaml_str

    # {{{ process non-block-scalar YAML lines through Jinja

    block_var_num = [0]
    block_vars = {}
    block_name_template = "_RELATE_JINJA_BLOCK_SUB_%d"

    lines = yaml_str.split("\n")
    jinja_lines = []

    def add_unprocessed_block(s):
        my_block_num = block_var_num[0]
        block_var_num[0] += 1

        my_block_name = block_name_template % my_block_num
        block_vars[my_block_name] = s
        jinja_lines.append("{{ %s }}" % my_block_name)

    i = 0
    line_count = len(lines)

    while i < line_count:
        l = lines[i]
        if GROUP_COMMENT_START.match(l):
            add_unprocessed_block(l)
            i += 1

        elif YAML_BLOCK_START_SCALAR_RE.search(l):
            unprocessed_block_lines = []
            unprocessed_block_lines.append(l)

            block_start_indent = len(LEADING_SPACES_RE.match(l).group(1))

            i += 1

            while i < line_count:
                l = lines[i]

                if not l.rstrip():
                    unprocessed_block_lines.append(l)
                    i += 1
                    continue

                line_indent = len(LEADING_SPACES_RE.match(l).group(1))
                if line_indent <= block_start_indent:
                    break
                else:
                    unprocessed_block_lines.append(l)
                    i += 1

            add_unprocessed_block("\n".join(unprocessed_block_lines))

        else:
            jinja_lines.append(l)
            i += 1

    jinja_str = "\n".join(jinja_lines)

    template = jinja_env.from_string(jinja_str)
    yaml_str = template.render(block_vars)

    # }}}

    return yaml_str


def get_raw_yaml_from_repo(repo, full_name, commit_sha):
    """Return decoded YAML data structure from
    the given file in *repo* at *commit_sha*.

    :arg commit_sha: A byte string containing the commit hash
    """

    from six.moves.urllib.parse import quote_plus
    cache_key = "%RAW%%2".join((
        quote_plus(repo.controldir()), quote_plus(full_name), commit_sha.decode()))

    import django.core.cache as cache
    def_cache = cache.caches["default"]
    result = None
    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        result = def_cache.get(cache_key)
    if result is not None:
        return result

    result = load_yaml(
            expand_yaml_macros(
                repo, commit_sha,
                get_repo_blob(repo, full_name, commit_sha).data))

    def_cache.add(cache_key, result, None)

    return result


def get_yaml_from_repo(repo, full_name, commit_sha, cached=True):
    """Return decoded, struct-ified YAML data structure from
    the given file in *repo* at *commit_sha*.

    See :class:`relate.utils.Struct` for more on
    struct-ification.
    """

    if cached:
        from six.moves.urllib.parse import quote_plus
        cache_key = "%%%2".join(
                (quote_plus(repo.controldir()), quote_plus(full_name),
                    commit_sha.decode()))

        import django.core.cache as cache
        def_cache = cache.caches["default"]
        result = None
        # Memcache is apparently limited to 250 characters.
        if len(cache_key) < 240:
            result = def_cache.get(cache_key)
        if result is not None:
            return result

    expanded = expand_yaml_macros(
            repo, commit_sha,
            get_repo_blob(repo, full_name, commit_sha).data)

    result = dict_to_struct(load_yaml(expanded))

    if cached:
        def_cache.add(cache_key, result, None)

    return result


def is_repo_file_accessible_as(access_kind, repo, commit_sha, path):
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    from os.path import dirname, basename, join
    attributes_path = join(dirname(path), ".attributes.yml")

    from course.content import get_raw_yaml_from_repo
    try:
        attributes = get_raw_yaml_from_repo(
                repo, attributes_path, commit_sha.encode())
    except ObjectDoesNotExist:
        # no attributes file: not public
        return False

    path_basename = basename(path)
    access_patterns = attributes.get(access_kind, [])

    from fnmatch import fnmatch
    if isinstance(access_patterns, list):
        for pattern in access_patterns:
            if isinstance(pattern, six.string_types):
                if fnmatch(path_basename, pattern):
                    return True

    return False

# }}}


# {{{ markup

def _attr_to_string(key, val):
    if val is None:
        return key
    elif "\"" in val:
        return "%s='%s'" % (key, val)
    else:
        return "%s=\"%s\"" % (key, val)


class TagProcessingHTMLParser(html_parser.HTMLParser):
    def __init__(self, out_file, process_tag_func):
        html_parser.HTMLParser.__init__(self)

        self.out_file = out_file
        self.process_tag_func = process_tag_func

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<%s %s>" % (tag, " ".join(
            _attr_to_string(k, v) for k, v in six.iteritems(attrs))))

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
        raise NotImplementedError(
                _("I have no idea what a processing instruction is."))

    def unknown_decl(self, data):
        self.out_file.write("<![%s]>" % data)


class LinkFixerTreeprocessor(Treeprocessor):
    def __init__(self, md, course, commit_sha, reverse_func):
        Treeprocessor.__init__(self)
        self.md = md
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def get_course_identifier(self):
        if self.course is None:
            return "bogus-course-identifier"
        else:
            return self.course.identifier

    def process_url(self, url):
        if url.startswith("course:"):
            course_id = url[7:]
            if course_id:
                return self.reverse_func("relate-course_page",
                            args=(course_id,))
            else:
                return self.reverse_func("relate-course_page",
                            args=(self.get_course_identifier(),))

        elif url.startswith("flow:"):
            flow_id = url[5:]
            return self.reverse_func("relate-view_start_flow",
                        args=(self.get_course_identifier(), flow_id))

        elif url.startswith("media:"):
            media_path = url[6:]
            return self.reverse_func("relate-get_media",
                        args=(
                            self.get_course_identifier(),
                            self.commit_sha,
                            media_path))

        elif url.startswith("repo:"):
            path = url[5:]
            return self.reverse_func("relate-get_repo_file",
                        args=(
                            self.get_course_identifier(),
                            self.commit_sha,
                            path))

        elif url.startswith("repocur:"):
            path = url[8:]
            return self.reverse_func("relate-get_current_repo_file",
                        args=(
                            self.get_course_identifier(),
                            path))

        elif url.strip() == "calendar:":
            return self.reverse_func("relate-view_calendar",
                        args=(self.get_course_identifier(),))

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

        elif tag_name == "object" and "data" in attrs:
            new_data = self.process_url(attrs["data"])

            if new_data is not None:
                changed_attrs["data"] = new_data

        return changed_attrs

    def process_etree_element(self, element):
        changed_attrs = self.process_tag(element.tag, element.attrib)

        for key, val in six.iteritems(changed_attrs):
            element.set(key, val)

    def walk_and_process_tree(self, root):
        self.process_etree_element(root)

        for child in root:
            self.walk_and_process_tree(child)

    def run(self, root):
        self.walk_and_process_tree(root)

        # root through and process Markdown's HTML stash (gross!)
        from six.moves import cStringIO

        for i, (html, safe) in enumerate(self.md.htmlStash.rawHtmlBlocks):
            outf = cStringIO()
            parser = TagProcessingHTMLParser(outf, self.process_tag)
            parser.feed(html)

            self.md.htmlStash.rawHtmlBlocks[i] = (outf.getvalue(), safe)


class LinkFixerExtension(Extension):
    def __init__(self, course, commit_sha, reverse_func):
        Extension.__init__(self)
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def extendMarkdown(self, md, md_globals):  # noqa
        md.treeprocessors["relate_link_fixer"] = \
                LinkFixerTreeprocessor(md, self.course, self.commit_sha,
                        reverse_func=self.reverse_func)


class GitTemplateLoader(BaseTemplateLoader):
    def __init__(self, repo, commit_sha):
        self.repo = repo
        self.commit_sha = commit_sha

    def get_source(self, environment, template):
        try:
            data = get_repo_blob_data_cached(self.repo, template, self.commit_sha)
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


def markup_to_html(course, repo, commit_sha, text, reverse_func=None,
        validate_only=False, jinja_env={}):
    if reverse_func is None:
        from django.core.urlresolvers import reverse
        reverse_func = reverse

    if course is not None and not jinja_env:
        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            cache_key = None
        else:
            import hashlib
            cache_key = ("markup:%d:%s:%s"
                    % (course.id, str(commit_sha),
                        hashlib.md5(text.encode("utf-8")).hexdigest()))

            def_cache = cache.caches["default"]
            result = def_cache.get(cache_key)
            if result is not None:
                return result

        if text.lstrip().startswith(JINJA_PREFIX):
            text = remove_prefix(JINJA_PREFIX, text.lstrip())
    else:
        cache_key = None

    # {{{ process through Jinja

    from jinja2 import Environment, StrictUndefined
    env = Environment(
            loader=GitTemplateLoader(repo, commit_sha),
            undefined=StrictUndefined)
    template = env.from_string(text)
    text = template.render(**jinja_env)

    # }}}

    if validate_only:
        return

    from course.mdx_mathjax import MathJaxExtension
    import markdown
    result = markdown.markdown(text,
        extensions=[
            LinkFixerExtension(course, commit_sha, reverse_func=reverse_func),
            MathJaxExtension(),
            "markdown.extensions.extra",
            "markdown.extensions.codehilite",
            ],
        output_format="html5")

    if cache_key is not None:
        def_cache.add(cache_key, result, None)

    return result

# }}}


DATE_RE = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
TRAILING_NUMERAL_RE = re.compile(r"^(.*)\s+([0-9]+)$")


class InvalidDatespec(ValueError):
    def __init__(self, datespec):
        ValueError.__init__(self, str(datespec))
        self.datespec = datespec


AT_TIME_RE = re.compile(r"^(.*)\s*@\s*([0-2]?[0-9])\:([0-9][0-9])\s*$")


class AtTimePostprocessor(object):
    def __init__(self, hour, minute, second=0):
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


class PlusDeltaPostprocessor(object):
    def __init__(self, count, period):
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
        elif self.period.startswith("minute"):
            d = datetime.timedelta(minutes=self.count)
        else:
            raise InvalidDatespec(_("invalid period: %s" % self.period))

        return dtm + d


DATESPEC_POSTPROCESSORS = [
        AtTimePostprocessor,
        PlusDeltaPostprocessor,
        ]


def parse_date_spec(course, datespec, vctx=None, location=None):
    if datespec is None:
        return None

    orig_datespec = datespec

    def localize_if_needed(d):
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

    datespec = datespec.strip()

    # {{{ parse postprocessors

    postprocs = []
    while True:
        parsed_one = False
        for pp_class in DATESPEC_POSTPROCESSORS:
            datespec, postproc = pp_class.parse(datespec)
            if postproc is not None:
                parsed_one = True
                postprocs.insert(0, postproc)
                break

        datespec = datespec.strip()

        if not parsed_one:
            break

    # }}}

    def apply_postprocs(dtime):
        for postproc in postprocs:
            dtime = postproc.apply(dtime)

        return dtime

    match = DATE_RE.match(datespec)
    if match:
        result = datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)))
        result = localize_if_needed(
                datetime.datetime.combine(result, datetime.time.min))
        return apply_postprocs(result)

    match = TRAILING_NUMERAL_RE.match(datespec)
    if match:
        if vctx is not None:
            from course.validation import validate_identifier
            validate_identifier(vctx, "%s: event kind" % location,
                    match.group(1))

        if course is None:
            return now()

        from course.models import Event
        try:
            return apply_postprocs(
                    Event.objects.get(
                        course=course,
                        kind=match.group(1),
                        ordinal=int(match.group(2))).time)

        except ObjectDoesNotExist:
            if vctx is not None:
                vctx.add_warning(
                        location,
                        _("unrecognized date/time specification: '%s' "
                        "(interpreted as 'now')")
                        % orig_datespec)
            return now()

    if vctx is not None:
        from course.validation import validate_identifier
        validate_identifier(vctx, "%s: event kind" % location, datespec)

    if course is None:
        return now()

    from course.models import Event

    try:
        return apply_postprocs(
                Event.objects.get(
                    course=course,
                    kind=datespec,
                    ordinal=None).time)

    except ObjectDoesNotExist:
        if vctx is not None:
            vctx.add_warning(
                    location,
                    _("unrecognized date/time specification: '%s' "
                    "(interpreted as 'now')")
                    % orig_datespec)
        return now()


def compute_chunk_weight_and_shown(course, chunk, role, now_datetime,
        remote_address):
    for rule in chunk.rules:
        if hasattr(rule, "if_has_role"):
            if role not in rule.if_has_role:
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
            from course.utils import is_address_in_facility
            if not is_address_in_facility(remote_address, rule.if_in_facility):
                continue

        # {{{ deprecated

        if hasattr(rule, "roles"):
            if role not in rule.roles:
                continue

        if hasattr(rule, "start"):
            start_date = parse_date_spec(course, rule.start)
            if now_datetime < start_date:
                continue

        if hasattr(rule, "end"):
            end_date = parse_date_spec(course, rule.end)
            if end_date < now_datetime:
                continue

        # }}}

        shown = True
        if hasattr(rule, "shown"):
            shown = rule.shown

        return rule.weight, shown

    return 0, True


def get_course_desc(repo, course, commit_sha):
    return get_yaml_from_repo(repo, course.course_file, commit_sha)


def get_processed_course_chunks(course, repo, commit_sha,
        course_desc, role, now_datetime, remote_address):
    for chunk in course_desc.chunks:
        chunk.weight, chunk.shown = \
                compute_chunk_weight_and_shown(
                        course, chunk, role, now_datetime,
                        remote_address)
        chunk.html_content = markup_to_html(course, repo, commit_sha, chunk.content)

    course_desc.chunks.sort(key=lambda chunk: chunk.weight, reverse=True)

    return [chunk for chunk in course_desc.chunks
            if chunk.shown]


def normalize_flow_desc(flow_desc):
    if hasattr(flow_desc, "pages"):
        pages = flow_desc.pages
        from relate.utils import struct_to_dict, Struct
        d = struct_to_dict(flow_desc)
        del d["pages"]
        d["groups"] = [Struct({"id": "main", "pages": pages})]
        return Struct(d)

    if hasattr(flow_desc, "rules"):
        rules = flow_desc.rules
        if not hasattr(rules, "grade_identifier"):
            # Legacy content with grade_identifier in grading rule,
            # move first found grade_identifier up to rules.

            rules.grade_identifier = None
            rules.grade_aggregation_strategy = None

            for grule in rules.grading:
                if grule.grade_identifier is not None:
                    rules.grade_identifier = grule.grade_identifier
                    rules.grade_aggregation_strategy = \
                            grule.grade_aggregation_strategy
                    break

    return flow_desc


def get_flow_desc(repo, course, flow_id, commit_sha):
    flow_desc = get_yaml_from_repo(repo, "flows/%s.yml" % flow_id, commit_sha)

    flow_desc = normalize_flow_desc(flow_desc)

    flow_desc.description_html = markup_to_html(
            course, repo, commit_sha, getattr(flow_desc, "description", None))
    return flow_desc


def get_flow_page_desc(flow_id, flow_desc, group_id, page_id):
    for grp in flow_desc.groups:
        if grp.id == group_id:
            for page in grp.pages:
                if page.id == page_id:
                    return page

    raise ObjectDoesNotExist(
            _("page '%(group_id)s/%(page_id)s' in flow '%(flow_id)s'") % {
                'group_id': group_id,
                'page_id': page_id,
                'flow_id': flow_id
                })


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
            raise ClassNotFoundError(
                    _("repo page class must conist of two "
                    "dotted components (invalid: '%s')")
                    % typename)

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

    return class_(None, location, page_desc)


def _adjust_flow_session_page_data_inner(repo, flow_session,
        course_identifier, flow_desc):
    commit_sha = get_course_commit_sha(
            flow_session.course, flow_session.participation)

    from course.models import FlowPageData

    def remove_page(fpd):
        if fpd.ordinal is not None:
            fpd.ordinal = None
            fpd.save()

    desc_group_ids = []

    ordinal = [0]
    for grp in flow_desc.groups:
        desc_group_ids.append(grp.id)

        shuffle = getattr(grp, "shuffle", False)
        max_page_count = getattr(grp, "max_page_count", None)

        available_page_ids = [page_desc.id for page_desc in grp.pages]

        if max_page_count is None:
            max_page_count = len(available_page_ids)

        group_pages = []

        # {{{ helper functions

        def find_page_desc(page_id):
            new_page_desc = None

            for page_desc in grp.pages:
                if page_desc.id == page_id:
                    new_page_desc = page_desc
                    break

            assert new_page_desc is not None

            return new_page_desc

        def create_fpd(new_page_desc):
            page = instantiate_flow_page(
                    "course '%s', flow '%s', page '%s/%s'"
                    % (course_identifier, flow_session.flow_id,
                        grp.id, new_page_desc.id),
                    repo, new_page_desc, commit_sha)

            return FlowPageData(
                    flow_session=flow_session,
                    group_id=grp.id,
                    page_id=new_page_desc.id,
                    ordinal=None,
                    data=page.make_page_data())

        def add_page(fpd):
            if fpd.ordinal != ordinal[0]:
                fpd.ordinal = ordinal[0]
                fpd.save()

            ordinal[0] += 1
            available_page_ids.remove(fpd.page_id)
            group_pages.append(fpd)

        # }}}

        if shuffle:
            # maintain order of existing pages as much as possible
            for fpd in (FlowPageData.objects
                    .filter(
                        flow_session=flow_session,
                        group_id=grp.id,
                        ordinal__isnull=False)
                    .order_by("ordinal")):

                if (fpd.page_id in available_page_ids
                        and len(group_pages) < max_page_count):
                    add_page(fpd)
                else:
                    remove_page(fpd)

            assert len(group_pages) <= max_page_count

            from random import choice

            # then add randomly chosen new pages
            while len(group_pages) < max_page_count and available_page_ids:
                new_page_id = choice(available_page_ids)

                new_page_fpds = (FlowPageData.objects
                        .filter(
                            flow_session=flow_session,
                            group_id=grp.id,
                            page_id=new_page_id))

                if new_page_fpds.count():
                    # We already have FlowPageData for this page, revive it
                    new_page_fpd, = new_page_fpds
                    assert new_page_fpd.id == new_page_id
                else:
                    # Make a new FlowPageData instance
                    page_desc = find_page_desc(new_page_id)
                    assert page_desc.id == new_page_id
                    new_page_fpd = create_fpd(page_desc)
                    assert new_page_fpd.page_id == new_page_id

                add_page(new_page_fpd)

        else:
            # reorder pages to order in flow
            id_to_fpd = dict(
                    ((fpd.group_id, fpd.page_id), fpd)
                    for fpd in FlowPageData.objects.filter(
                        flow_session=flow_session,
                        group_id=grp.id))

            for page_desc in grp.pages:
                key = (grp.id, page_desc.id)

                if key in id_to_fpd:
                    fpd = id_to_fpd.pop(key)
                else:
                    fpd = create_fpd(page_desc)

                if len(group_pages) < max_page_count:
                    add_page(fpd)

            for fpd in id_to_fpd.values():
                remove_page(fpd)

    # {{{ remove pages orphaned because of group renames

    for fpd in (
            FlowPageData.objects
            .filter(
                flow_session=flow_session,
                ordinal__isnull=False)
            .exclude(group_id__in=desc_group_ids)
            ):
        remove_page(fpd)

    # }}}

    if flow_session.page_count != ordinal[0]:
        flow_session.page_count = ordinal[0]
        flow_session.save()


def adjust_flow_session_page_data(repo, flow_session,
        course_identifier, flow_desc):
    # The atomicity is not done as a decorator above because we can't import
    # django.db at the module level here. The relate-validate script wants to
    # import this module, and it obviously has no database.

    from django.db import transaction
    with transaction.atomic():
        return _adjust_flow_session_page_data_inner(
                repo, flow_session, course_identifier, flow_desc)


def get_course_commit_sha(course, participation):
    sha = course.active_git_commit_sha

    if participation is not None and participation.preview_git_commit_sha:
        sha = participation.preview_git_commit_sha

    return sha.encode()


def list_flow_ids(repo, commit_sha):
    flow_ids = []
    try:
        flows_tree = get_repo_blob(repo, "flows", commit_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in flows_tree.items():
            if entry.path.endswith(b".yml"):
                flow_ids.append(entry.path[:-4])

    return sorted(flow_ids)

# vim: foldmethod=marker
