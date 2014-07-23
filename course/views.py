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

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
from django.core.exceptions import PermissionDenied, SuspiciousOperation

import datetime

from course.models import (
        Course, Participation,
        FlowAccessException,
        FlowVisit,
        participation_role, participation_status)

from course.content import (
        get_course_repo, get_course_desc, parse_date_spec,
        get_flow_desc
        )


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


def get_flow_permissions(course_desc, participation, role, flow_id, flow_desc):
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

    for rule in flow_desc.access_rules:
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


# {{{ home

def home(request):
    courses_and_descs_and_invalid_flags = []
    for course in Course.objects.all():
        repo = get_course_repo(course)
        desc = get_course_desc(repo, course.active_git_commit_sha.encode())

        role, participation = get_role_and_participation(request, course)

        show = True
        if course.hidden:
            if role not in [participation_role.teaching_assistant,
                    participation_role.instructor]:
                show = False

        if not course.valid:
            if role != participation_role.instructor:
                show = False

        if show:
            courses_and_descs_and_invalid_flags.append(
                    (course, desc, not course.valid))

    def course_sort_key(entry):
        course, desc, invalid_flag = entry
        return desc.course_start

    courses_and_descs_and_invalid_flags.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs_and_invalid_flags": courses_and_descs_and_invalid_flags
        })

# }}}


# {{{ course page

def check_course_state(course, role):
    if course.hidden:
        if role not in [participation_role.teaching_assistant,
                participation_role.instructor]:
            raise PermissionDenied("only course staff have access")
    elif not course.valid:
        if role != participation_role.instructor:
            raise PermissionDenied("only the instructor has access")


def course_page(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    check_course_state(course, role)

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

# }}}


class FlowContext(object):
    def __init__(self, request, course_identifier, flow_identifier, flow_visit=None):
        self.flow_visit = flow_visit

        self.course_identifier = course_identifier
        self.flow_identifier = flow_identifier

        self.course = get_object_or_404(Course, identifier=course_identifier)
        self.role, self.participation = get_role_and_participation(
                request, self.course)

        check_course_state(self.course, self.role)

        if self.flow_visit is not None:
            self.commit_sha = self.flow_visit.active_git_commit_sha.encode()
        else:
            self.commit_sha = get_active_commit_sha(self.course, self.participation)

        self.repo = get_course_repo(self.course)
        self.course_desc = get_course_desc(self.repo, self.commit_sha)

        self.flow_desc = get_flow_desc(self.repo, self.course,
                flow_identifier, self.commit_sha)

        self.permissions, self.stipulations = get_flow_permissions(
                self.course_desc, self.participation, self.role,
                flow_identifier, self.flow_desc)

    def will_receive_feedback(self):
        from course.models import flow_permission
        return (
                flow_permission.see_correctness in self.permissions
                or flow_permission.see_answer in self.permissions)


def start_flow(request, course_identifier, flow_identifier):
    fctx = FlowContext(request, course_identifier, flow_identifier)

    from course.models import flow_permission
    if flow_permission.view not in fctx.permissions:
        raise PermissionDenied()

    if request.method == "POST":
        from course.content import set_up_flow_visit_page_data

        if ("start_no_credit" in request.POST
                or "start_credit" in request.POST):
            visit = FlowVisit()
            visit.participation = fctx.participation
            visit.active_git_commit_sha = fctx.commit_sha.decode()
            visit.flow_id = flow_identifier
            visit.in_progress = True
            visit.for_credit = "start_credit" in request.POST
            visit.save()

            request.session["flow_visit_id"] = visit.id

            page_count = set_up_flow_visit_page_data(fctx.repo, visit,
                    fctx.flow_desc, fctx.commit_sha)
            visit.page_count = page_count
            visit.save()

            return redirect("course.views.view_flow_page",
                    course_identifier,
                    flow_identifier,
                    0)

        else:
            raise SuspiciousOperation("unrecognized POST action")

    else:
        can_start_credit = flow_permission.start_credit in fctx.permissions
        can_start_no_credit = flow_permission.start_no_credit in fctx.permissions

        # FIXME take into account max attempts
        # FIXME resumption
        # FIXME view past

        return render(request, "course/flow-start.html", {
            "participation": fctx.participation,
            "course_desc": fctx.course_desc,
            "course": fctx.course,
            "flow_desc": fctx.flow_desc,
            "flow_identifier": flow_identifier,
            "can_start_credit": can_start_credit,
            "can_start_no_credit": can_start_no_credit,
            })


class FlowPageContext(FlowContext):
    """This object acts as a container for all the information that a flow page
    may need to render itself or respond to a POST.
    """

    def __init__(self, request, course_identifier, flow_identifier,
            ordinal, flow_visit):
        FlowContext.__init__(self, request, course_identifier, flow_identifier,
                flow_visit=flow_visit)

        from course.models import FlowPageData
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_visit=flow_visit, ordinal=ordinal)

        from course.content import get_flow_page_desc
        self.page_desc = get_flow_page_desc(
                flow_visit, self.flow_desc, page_data.group_id, page_data.page_id)

        from course.content import instantiate_flow_page
        self.page = instantiate_flow_page(
                "course '%s', flow '%s', page '%s/%s'"
                % (course_identifier, flow_identifier,
                    page_data.group_id, page_data.page_id),
                self.repo, self.page_desc, self.commit_sha)

        from course.page import PageContext
        self.page_context = PageContext(
                course=self.course,
                ordinal=page_data.ordinal,
                page_count=flow_visit.page_count,
                )

        # {{{ dig for previous answers

        from course.models import FlowPageVisit
        previous_answer_visits = (FlowPageVisit.objects
                .filter(flow_visit=flow_visit)
                .filter(page_data=page_data)
                .filter(answer__isnull=False)
                .order_by("-visit_time"))

        self.prev_answer_is_final = False
        self.prev_answer = None
        for prev_visit in previous_answer_visits:
            self.prev_answer = prev_visit.answer
            self.prev_answer_is_final = prev_visit.answer_is_final
            break

        # }}}

    @property
    def ordinal(self):
        return self.page_data.ordinal

    @property
    def page_count(self):
        return self.flow_visit.page_count

    @property
    def percentage(self):
        return int(100*(self.ordinal+1)/self.page_count)

    def create_visit(self):
        from course.models import FlowPageVisit

        page_visit = FlowPageVisit()
        page_visit.flow_visit = self.flow_visit
        page_visit.page_data = self.page_data
        page_visit.save()


def find_current_flow_visit(request, flow_identifier):
    flow_visit = None
    flow_visit_id = request.session.get("flow_visit_id")

    if flow_visit_id is not None:
        flow_visits = list(FlowVisit.objects.filter(id=flow_visit_id))

        if flow_visits and flow_visits[0].flow_id == flow_identifier:
            flow_visit, = flow_visits

        if not flow_visit.in_progress:
            flow_visit = False

    return flow_visit


def render_flow_page(request, fpctx, **kwargs):
    args = {
        "course": fpctx.course,
        "course_desc": fpctx.course_desc,
        "flow_identifier": fpctx.flow_identifier,
        "flow_desc": fpctx.flow_desc,
        "ordinal": fpctx.ordinal,
        "page_data": fpctx.page_data,
        "percentage": fpctx.percentage,
        "flow_visit": fpctx.flow_visit,
        "participation": fpctx.participation,
    }

    args.update(kwargs)

    return render(request, "course/flow-page.html", args)


def add_buttons_to_form(fpctx, form):
    from crispy_forms.layout import Submit
    form.helper.add_input(
            Submit("save", "Save answer",
                css_class="col-lg-offset-2"))

    if fpctx.will_receive_feedback():
        form.helper.add_input(Submit("submit", "Submit final answer"))
    else:
        # Only offer 'save and move on' if student will receive no feedback
        if fpctx.page_data.ordinal + 1 < fpctx.flow_visit.page_count:
            form.helper.add_input(
                    Submit("save_and_next", "Save answer and move on"))
        else:
            form.helper.add_input(
                    Submit("save_and_finish", "Save answer and finish"))

    return form


def get_pressed_button(form):
    buttons = ["save", "save_and_next", "save_and_finish", "submit"]
    for button in buttons:
        if button in form.data:
            return button

    raise SuspiciousOperation("could not find which button was pressed")


def view_flow_page(request, course_identifier, flow_identifier, ordinal):
    flow_visit = find_current_flow_visit(request, flow_identifier)

    if flow_visit is None:
        messages.add_message(request, messages.WARNING,
                "No in-progress visit record found for this flow. "
                "Redirected to flow start page.")

        return redirect("course.views.start_flow",
                course_identifier,
                flow_identifier)

    fpctx = FlowPageContext(request, course_identifier, flow_identifier,
            ordinal, flow_visit)

    page_context = fpctx.page_context
    page_data = fpctx.page_data

    from course.models import FlowPageVisit, flow_permission

    if flow_permission.view not in fpctx.permissions:
        raise PermissionDenied("not allowed to view flow")

    if request.method == "POST":
        if "finish" in request.POST:
            return redirect("course.views.finish_flow",
                    course_identifier, flow_identifier)
        else:
            # reject if previous answer was final
            if fpctx.prev_answer_is_final:
                raise PermissionDenied("already have final answer")

            form = fpctx.page.post_form(fpctx.page_context, fpctx.page_data.data,
                    post_data=request.POST, files_data=request.POST)

            pressed_button = get_pressed_button(form)

            if form.is_valid():
                # {{{ form validated, process answer

                messages.add_message(request, messages.INFO,
                        "Answer saved.")

                page_visit = FlowPageVisit()
                page_visit.flow_visit = fpctx.flow_visit
                page_visit.page_data = fpctx.page_data
                page_visit.answer = fpctx.page.make_answer_data(
                        fpctx.page_context, fpctx.page_data.data,
                        form)
                page_visit.answer_is_final = pressed_button == "submit"
                page_visit.save()

                answer_data = page_visit.answer
                answer_is_final = page_visit.answer_is_final

                if (pressed_button == "save_and_next"
                        and not fpctx.will_receive_feedback()):
                    return redirect("course.views.view_flow_page",
                            course_identifier,
                            flow_identifier,
                            fpctx.ordinal + 1)
                elif (pressed_button == "save_and_finish"
                        and not fpctx.will_receive_feedback()):
                    return redirect("course.views.finish_flow",
                            course_identifier, flow_identifier)
                else:
                    # continue at common flow page generation below

                    form = fpctx.page.form_with_answer(page_context, page_data.data,
                            page_visit.answer, page_visit.answer_is_final)

                    # continue at common flow page generation below

                # }}}

            else:
                # form did not validate

                fpctx.create_visit()

                answer_data = None
                answer_is_final = False

                # continue at common flow page generation below

    else:
        fpctx.create_visit()

        answer_data = fpctx.prev_answer
        answer_is_final = fpctx.prev_answer_is_final

        if answer_data:
            form = fpctx.page.form_with_answer(page_context, page_data.data,
                    answer_data, answer_is_final)

        else:
            form = fpctx.page.fresh_form(page_context, page_data.data)

    # start common flow page generation

    # defined at this point: form, answer_data, answer_is_final

    if form is not None and not answer_is_final:
        form = add_buttons_to_form(fpctx, form)

    show_correctness = None
    show_answer = None
    feedback = None

    if (answer_data is not None
            and answer_is_final):
        show_correctness = flow_permission.see_correctness in fpctx.permissions
        show_answer = flow_permission.see_answer in fpctx.permissions

        if show_correctness or show_answer:
            feedback = fpctx.page.grade(page_context, page_data.data, answer_data)

    title = fpctx.page.title(page_context, page_data.data)
    body = fpctx.page.body(page_context, page_data.data)

    return render_flow_page(
            request, fpctx, title=title, body=body, form=form,
            feedback=feedback,
            show_correctness=show_correctness,
            show_answer=show_answer)


def finish_flow(request, course_identifier, flow_identifier):
    flow_visit = find_current_flow_visit(request, flow_identifier)

    if flow_visit is None:
        messages.add_message(request, messages.WARNING,
                "No in-progress visit record found for this flow. "
                "Redirected to flow start page.")

        return redirect("course.views.start_flow",
                course_identifier,
                flow_identifier)

    fctx = FlowContext(request, course_identifier, flow_identifier,
            flow_visit=flow_visit)

    request.session["flow_visit_id"] = None

    from django.utils.timezone import now
    flow_visit.completion_time = now()
    flow_visit.in_progress = False
    flow_visit.save()

    # FIXME confirm, ask about unanswered questions
    # FIXME mark answers as final
    # FIXME assign grade
    # FIXME show grade

    from course.content import html_body
    return render(request, "course/flow-completion.html", {
        "course": fctx.course,
        "course_desc": fctx.course_desc,
        "flow_identifier": fctx.flow_identifier,
        "flow_desc": fctx.flow_desc,
        "body": html_body(fctx.course, fctx.flow_desc.completion_text),
        "participation": fctx.participation,
    })



# }}}

# vim: foldmethod=marker
