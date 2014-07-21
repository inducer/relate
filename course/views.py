from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
import django.forms as forms

from django.core.exceptions import PermissionDenied

import datetime

from course.models import (
        Course, Participation,
        participation_role, participation_status)
from course.content import (
        get_course_repo, get_course_desc, parse_date_spec,
        get_flow
        )

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit


def get_role_and_participation(request, course):
    # "wake up" lazy object
    # http://stackoverflow.com/questions/20534577/int-argument-must-be-a-string-or-a-number-not-simplelazyobject  # noqa
    user = (request.user._wrapped
            if hasattr(request.user, '_wrapped')
            else request.user)

    if not user.is_authenticated():
        return participation_role.unenrolled, None

    participations = list(Participation.objects.filter(
            user=user, course=course))

    # The uniqueness constraint should have ensured that.
    assert len(participations) <= 1

    if len(participations) == 0:
        return participation_role.unenrolled, None

    participation = participations[0]
    if participation.status != participation_status.active:
        return participation_role.unenrolled, participation
    else:
        if participation.temporary_role:
            return participation.temporary_role, participation
        else:
            return participation.role, participation


def get_active_commit_sha(course, participation):
    sha = course.active_git_commit_sha

    if participation is not None and participation.preview_git_commit_sha:
        sha = participation.preview_git_commit_sha

    return sha.encode()


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
    visits = (FlowVisit.objects
            .filter(participation=participation)
            .order_by("-start_time"))


# {{{ views

def home(request):
    courses_and_descs = []
    for course in Course.objects.all():
        repo = get_course_repo(course)
        desc = get_course_desc(repo, course.active_git_commit_sha.encode())
        courses_and_descs.append((course, desc))

    def course_sort_key(entry):
        course, desc = entry
        return desc.course_start

    courses_and_descs.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs": courses_and_descs
        })


def sign_in_by_email(request):
    # FIXME
    raise NotImplementedError()


def course_page(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(course, course_desc,
            role)

    return render(request, "course/course-page.html", {
        "course": course,
        "course_desc": course_desc,
        "participation": participation,
        "role": role,
        "chunks": chunks,
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

    course_desc = get_course_desc(course)

    flow = get_flow(course, flow_identifier, active_git_commit_sha)

    access = get_flow_access(course_desc, role, flow, None)

    if access.what == "deny":
        messages.add_message(request, messages.WARNING,
                "Access denied")
        return render(request, "course/course-base.html",
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
    course_desc = get_course_desc(course)

    return render(request, "course/flow-page.html", {
        "course": course,
        "course_desc": course_desc,
        #"flow_desc": flow_desc,
        })


def enroll(request, course_identifier):
    # FIXME
    raise NotImplementedError()


# {{{ git interaction

def fetch_course_updates(request, course_identifier):
    import sys

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.instructor:
        return PermissionDenied("must be instructor to update course")

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    was_successful = True
    log_lines = []
    try:
        repo = get_course_repo(course)

        if not course.git_source:
            raise RuntimeError("no git source URL specified")

        if course.ssh_private_key:
            repo.auth(pkey=course.ssh_private_key.encode("ascii"))

        log_lines.append("Pre-fetch head is at '%s'" % repo.head())

        from dulwich.client import get_transport_and_path
        client, remote_path = get_transport_and_path(course.git_source.encode())
        remote_refs = client.fetch(remote_path, repo)
        repo["HEAD"] = remote_refs["HEAD"]

        log_lines.append("Post-fetch head is at '%s'" % repo.head())

    except Exception:
        was_successful = False
        from traceback import format_exception
        log = "\n".join(log_lines) + "".join(
                format_exception(*sys.exc_info()))
    else:
        log = "\n".join(log_lines)

    return render(request, 'course/course-bulk-result.html', {
        "process_description": "Fetch course updates via git",
        "log": log,
        "status": "Pull successful."
            if was_successful
            else "Pull failed. See above for error.",
        "was_successful": was_successful,
        "course": course,
        "course_desc": course_desc,
        })


class GitUpdateForm(forms.Form):
    new_sha = forms.CharField(required=True, initial=50)

    def __init__(self, previewing, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        if previewing:
            self.helper.add_input(
                    Submit("end_preview", "End preview",
                        css_class="col-lg-offset-2"))
        else:
            self.helper.add_input(
                    Submit("preview", "Validate and preview",
                        css_class="col-lg-offset-2"))

        self.helper.add_input(
                Submit("update", "Validate and update"))
        super(GitUpdateForm, self).__init__(*args, **kwargs)


def update_course(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)

    course_desc = get_course_desc(repo, commit_sha)

    previewing = bool(participation.preview_git_commit_sha)

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(previewing, request.POST, request.FILES)
        if "end_preview" in form.data:
            messages.add_message(request, messages.INFO,
                    "Preview ended.")
            participation.preview_git_commit_sha = None
            participation.save()

            previewing = False

        elif form.is_valid():
            new_sha = form.cleaned_data["new_sha"].encode("utf-8")

            from course.content import validate_course_content
            from course.content import ValidationError
            try:
                validate_course_content(repo, new_sha)
            except ValidationError as e:
                messages.add_message(request, messages.ERROR,
                        "Course content did not validate successfully. (%s) "
                        "Update not applied."
                        % str(e))
                validated = False
            else:
                messages.add_message(request, messages.INFO,
                        "Course content validated successfully.")
                validated = True

            if validated and "update" in form.data:
                messages.add_message(request, messages.INFO,
                        "Update applied.")

                course.active_git_commit_sha = new_sha
                course.save()

                response_form = form

            elif validated and "preview" in form.data:
                messages.add_message(request, messages.INFO,
                        "Preview activated.")

                participation.preview_git_commit_sha = new_sha
                participation.save()

                previewing = True

    if response_form is None:
        form = GitUpdateForm(previewing,
                {"new_sha": repo.head()})

    text_lines = [
            "<b>Current git HEAD:</b> %s (%s)" % (
                repo.head(),
                repo[repo.head()].message),
            "<b>Public active git SHA:</b> %s (%s)" % (
                course.active_git_commit_sha,
                repo[course.active_git_commit_sha.encode()].message),
            ]
    if participation.preview_git_commit_sha:
        text_lines.append(
            "<b>Current preview git SHA:</b> %s (%s)" % (
                participation.preview_git_commit_sha,
                repo[participation.preview_git_commit_sha.encode()].message,
            ))
    else:
        text_lines.append("<b>Current preview git SHA:</b> None")

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_text": "".join(
            "<p>%s</p>" % line
            for line in text_lines
            ),
        "form_description": "Update Course Revision",
        "course": course,
        "course_desc": course_desc,
    })


# }}}

# }}}

# vim: foldmethod=marker
