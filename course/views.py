from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
import django.forms as forms

from django.core.exceptions import PermissionDenied, SuspiciousOperation

import datetime

from course.models import (
        Course, Participation,
        FlowAccessException,
        FlowVisit,
        participation_role, participation_status, flow_visit_state)

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


def get_flow_permissions(course_desc, participation, role, flow_id, flow):
    now = datetime.datetime.now().date()

    # {{{ scan for exceptions in database

    for exc in (
            FlowAccessException.objects
            .filter(participation=participation, flow_id=flow_id)
            .order_by("expiration")):

        if exc.expiration is not None and exc.expiration < now:
            continue

        stipulations = exc.stipulations
        if not isinstance(stipulations, dict):
            stipulations = {}
        from course.content import dict_to_struct
        stipulations = dict_to_struct(exc.stipulations)

        return (
                [entry.permission for entry in exc.entries.all()],
                stipulations
                )

    # }}}

    # {{{ interpret flow rules

    for rule in flow.access_rules:
        if hasattr(rule, "roles"):
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

        return rule.permissions, rule

    # }}}

    raise ValueError("Flow access rules of flow '%s' did not resolve "
            "to access answer for '%s'" % (flow_id, participation))


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


def enroll(request, course_identifier):
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


def start_flow(request, course_identifier, flow_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)
    course = get_object_or_404(Course, identifier=course_identifier)

    flow = get_flow(repo, course, flow_identifier, commit_sha)

    permissions, stipulations = get_flow_permissions(
            course_desc, participation, role, flow_identifier, flow)

    from course.models import flow_permission
    if flow_permission.view not in permissions:
        raise PermissionDenied()

    if request.method == "POST":
        from course.content import set_up_flow_visit_page_data

        if "start_credit" in request.POST:
            raise NotImplementedError("for-credit flows")
            # FIXME for-credit
        elif "start_no_credit" in request.POST:
            visit = FlowVisit()
            visit.participation = participation
            visit.active_git_commit_sha = commit_sha.decode()
            visit.flow_id = flow_identifier
            visit.state = flow_visit_state.in_progress
            visit.save()

            request.session["flow_visit_id"] = visit.id

            set_up_flow_visit_page_data(visit, flow)

            return redirect("course.views.view_flow_page",
                    course_identifier,
                    flow_identifier,
                    0)

        else:
            raise SuspiciousOperation("unrecognized POST action")

    else:
        can_start_credit = flow_permission.start_credit in permissions
        can_start_no_credit = flow_permission.start_no_credit in permissions

        # FIXME take into account max attempts
        # FIXME resumption
        # FIXME view past

        return render(request, "course/flow-start.html", {
            "participation": participation,
            "course_desc": course_desc,
            "course": course,
            "flow": flow,
            "flow_identifier": flow_identifier,
            "can_start_credit": can_start_credit,
            "can_start_no_credit": can_start_no_credit,
            })


def view_flow_page(request, course_identifier, flow_identifier, ordinal):
    flow_visit = None
    flow_visit_id = request.session.get("flow_visit_id")

    if flow_visit_id is not None:
        flow_visits = list(FlowVisit.objects.filter(id=flow_visit_id))

        if flow_visits and flow_visits[0].flow_id == flow_identifier:
            flow_visit, = flow_visits

    if flow_visit is None:
        messages.add_message(request, messages.WARNING,
                "No ongoing flow visit for this flow. "
                "Redirected to flow start page.")

        return redirect("course.views.start_flow",
                course_identifier,
                flow_identifier)

    # FIXME time limits

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = flow_visit.active_git_commit_sha.encode()

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    flow = get_flow(repo, course, flow_identifier, commit_sha)

    permissions, stipulations = get_flow_permissions(
            course_desc, participation, role, flow_identifier, flow)

    from course.model import FlowPageData, FlowPageVisit
    page_data = get_object_or_404(
            FlowPageData, flow_visit=flow_visit, ordinal=ordinal)

    from course.content import get_flow_page
    page = get_flow_page(flow_visit, flow, page_data.group_id, page_data.page_id)

    page_visit = FlowPageVisit()
    page_visit.page_data = page_data

    return render(request, "course/flow-page.html", {
        "course": course,
        "course_desc": course_desc,
        #"flow_desc": flow_desc,
        })


# {{{ git interaction

class GitFetchForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("fetch", "Fetch"))

        super(GitFetchForm, self).__init__(*args, **kwargs)


def fetch_course_updates(request, course_identifier):
    import sys

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.instructor:
        raise PermissionDenied("must be instructor to fetch revisisons")

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    form = GitFetchForm(request.POST, request.FILES)
    if request.method == "POST":
        if form.is_valid():
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
                client, remote_path = get_transport_and_path(
                        course.git_source.encode())
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
        else:
            form = GitFetchForm()
    else:
        form = GitFetchForm()

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_description": "Fetch New Course Revisions",
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
