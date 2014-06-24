from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
import django.forms as forms

from course.models import (
        Course, Participation,
        participation_role, participation_status)

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

import re
import datetime


def get_course_file(request, course, full_name, commit_sha=None):
    from os.path import join

    from gittle import Gittle
    repo = Gittle(join(settings.GIT_ROOT, course.identifier))

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


def get_role_and_participation(request, course):
    participations = Participation.objects.filter(
            user=request.user, course=course)

    if len(participations) > 1:
        messages.add_message(request, messages.WARNING,
                "Multiple enrollments found. Please contact the course staff.")

    if len(participations) == 0:
        return participation_role.unenrolled, None

    participation = participations[0]
    if participation.status != participation_status.active:
        return participation_role.unenrolled, participation
    else:
        return participation.role, participation


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


class AccessResult:
    def __init__(self, what, credit_percent):
        self.what = what
        self.credit_percent = credit_percent

        assert what in ["allow", "view", "deny"]


def get_flow_access(course_desc, role, flow, flow_visit):
    if flow_visit is not None:
        now = flow_visit.start_time.date()
    else:
        now = datetime.datetime.now().date()

    for rule in flow.access_rules:
        if role not in rule.roles:
            continue
        if hasattr(rule, "start"):
            start_date = parse_date_spec(course_desc, rule.start)
            if now < start_date:
                continue
        if hasattr(rule, "end"):
            end_date = parse_date_spec(course_desc, rule.end)
            if end_date < now:
                continue

        return AccessResult(rule.access, getattr(rule, "credit_percent", 100))

    return AccessResult("deny", 100)


def find_flow_visit(role, participation):
    return None


# {{{ views

def home(request):
    courses_and_descs = []
    for course in Course.objects.all():
        courses_and_descs.append(
                (course, get_course_desc(request, course)))

    courses_and_descs.sort(key=lambda (course, desc): desc.course_start)

    return render(request, "course/home.html", {
        "courses_and_descs": courses_and_descs
        })


def course_page(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)

    course_desc = get_course_desc(request, course)

    role, participation = get_role_and_participation(request, course)

    return render(request, "course/course-page.html", {
        "course": course,
        "ick": repr(course_desc),
        "course_desc": course_desc,
        "participation": participation,
        "role": role,
        "participation_role": participation_role,
        })


class StartForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"

        self.helper.add_input(
                Submit("submit", "Get started"))
        super(StartForm, self).__init__(*args, **kwargs)


def start_flow(request, course_identifier, flow_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)

    # TODO: Could be one of multiple
    fvisit = find_flow_visit(role, participation)
    if fvisit:
        active_git_commit_sha = fvisit.active_git_commit_sha
    else:
        active_git_commit_sha = course.active_git_commit_sha

    course_desc = get_course_desc(request, course)

    flow = get_flow(request, course, flow_identifier, active_git_commit_sha)

    access = get_flow_access(course_desc, role, flow, None)

    if access.what == "deny":
        messages.add_message(request, messages.WARNING,
                "Access denied")
        return render(request, "course/blank.html",
                {
                    "course": course,
                    "course_desc": course_desc,
                    },
                status=403)

    if request.method == "POST":
        if role != role.unenrolled:
            fvisit = FlowVisit()
            fvisit.participation = participation
            fvisit.active_git_commit_sha = course.active_git_commit_sha

    return render(request, "course/flow-start-page.html", {
        "course": course,
        "course_desc": course_desc,
        "flow": flow,
        "form": StartForm(),
        })


def view_flow_page(request, course_identifier, flow_identifier, page_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    course_desc = get_course_desc(request, course)

    return render(request, "course/flow-page.html", {
        "course": course,
        "course_desc": course_desc,
        #"flow_desc": flow_desc,
        })


def update_course(request, course_identifier):
    #head_sha = repo._commit_sha("HEAD")

    #if commit_sha != head_sha:
    # FIXME: only instructors should see this
    messages.add_message(request, messages.WARNING,
            "A new revision (%s) of the course data is available "
            "in the git repository." % head_sha)

# }}}

# vim: foldmethod=marker
