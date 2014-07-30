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
from django.db import transaction

import re

from course.models import (
        Course,
        FlowAccessException,
        FlowSession, FlowPageData, FlowPageVisit, flow_permission,
        GradeChange)

from course.content import (
        get_course_repo, get_course_desc, get_flow_desc,
        parse_date_spec
        )
from course.auth import get_role_and_participation
from course.views import check_course_state, get_active_commit_sha


def get_flow_permissions(course, participation, role, flow_id, flow_desc,
        now_datetime):
    # {{{ interpret flow rules

    flow_rule = None

    for rule in flow_desc.access_rules:
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

        flow_rule = rule
        break

    # }}}

    # {{{ scan for exceptions in database

    for exc in (
            FlowAccessException.objects
            .filter(participation=participation, flow_id=flow_id)
            .order_by("expiration")):

        if exc.expiration is not None and exc.expiration < now_datetime:
            continue

        exc_stipulations = exc.stipulations
        if not isinstance(exc_stipulations, dict):
            exc_stipulations = {}

        stipulations = {}

        if flow_rule is not None:
            stipulations.update(
                    (key, val)
                    for key, val in flow_rule.__dict__.iteritems()
                    if not key.startswith("_"))

        stipulations.update(exc_stipulations)
        from course.content import dict_to_struct
        stipulations = dict_to_struct(stipulations)

        return (
                [entry.permission for entry in exc.entries.all()],
                stipulations
                )

    # }}}

    if flow_rule is not None:
        return flow_rule.permissions, flow_rule

    raise ValueError("Flow access rules of flow '%s' did not resolve "
            "to access answer for '%s'" % (flow_id, participation))


# {{{ start flow

class FlowContext(object):
    def __init__(self, request, course_identifier, flow_identifier,
            flow_session=None):

        self.flow_session = flow_session

        self.course_identifier = course_identifier
        self.flow_identifier = flow_identifier

        self.course = get_object_or_404(Course, identifier=course_identifier)
        self.role, self.participation = get_role_and_participation(
                request, self.course)

        check_course_state(self.course, self.role)

        course_commit_sha = get_active_commit_sha(self.course, self.participation)
        if self.flow_session is not None:
            self.commit_sha = self.flow_session.active_git_commit_sha.encode()
        else:
            self.commit_sha = course_commit_sha

        self.repo = get_course_repo(self.course)
        self.course_desc = get_course_desc(self.repo, self.course, self.commit_sha)

        self.flow_desc = get_flow_desc(self.repo, self.course,
                flow_identifier, self.commit_sha)

        # {{{ figure out permissions

        # Fetch current version of the flow to compute permissions,
        # fall back to 'old' version if current git version does not
        # contain this flow any more.
        from django.core.exceptions import ObjectDoesNotExist

        try:
            permissions_flow_desc = get_flow_desc(self.repo, self.course,
                    flow_identifier, course_commit_sha)
        except ObjectDoesNotExist:
            permissions_flow_desc = self.flow_desc

        from course.views import get_now_or_fake_time
        self.permissions, self.stipulations = get_flow_permissions(
                self.course, self.participation, self.role,
                flow_identifier, permissions_flow_desc,
                get_now_or_fake_time(request))

        # }}}

    def will_receive_feedback(self):
        from course.models import flow_permission
        return (
                flow_permission.see_correctness in self.permissions
                or flow_permission.see_answer in self.permissions)

    @property
    def page_count(self):
        return self.flow_session.page_count


def instantiate_flow_page_with_ctx(fctx, page_data):
    from course.content import get_flow_page_desc
    page_desc = get_flow_page_desc(
            fctx.flow_session, fctx.flow_desc, page_data.group_id, page_data.page_id)

    from course.content import instantiate_flow_page
    return instantiate_flow_page(
            "course '%s', flow '%s', page '%s/%s'"
            % (fctx.course_identifier, fctx.flow_identifier,
                page_data.group_id, page_data.page_id),
            fctx.repo, page_desc, fctx.commit_sha)


RESUME_RE = re.compile("^resume_([0-9]+)$")


@transaction.atomic
def start_flow(request, course_identifier, flow_identifier):
    fctx = FlowContext(request, course_identifier, flow_identifier)

    from course.models import flow_permission
    if flow_permission.view not in fctx.permissions:
        raise PermissionDenied()

    have_in_progress_session = (FlowSession.objects
            .filter(
                participation=fctx.participation,
                flow_id=fctx.flow_identifier,
                in_progress=True
                )).count() > 0
    prior_ession_count = (FlowSession.objects
            .filter(
                participation=fctx.participation,
                flow_id=fctx.flow_identifier,
                )).count()

    if hasattr(fctx.stipulations, "allowed_session_count"):
        allowed_another_session = (
                prior_ession_count < fctx.stipulations.allowed_session_count)
    else:
        allowed_another_session = True

    if request.method == "POST":
        from course.content import set_up_flow_session_page_data

        resume_match = None
        for post_key in request.POST:
            resume_match = RESUME_RE.match(post_key)
            if resume_match is not None:
                break

        if resume_match is not None:
            resume_session_id = int(resume_match.group(1))

            resume_session = get_object_or_404(FlowSession, pk=resume_session_id)

            if resume_session.participation != fctx.participation:
                raise PermissionDenied("not your session")

            if resume_session.flow_id != fctx.flow_identifier:
                raise SuspiciousOperation("flow id mismatch on resume")

            if not (flow_permission.view_past in fctx.permissions
                    or resume_session.in_progress):
                raise PermissionDenied("not allowed to resume session")

            request.session["flow_session_id"] = resume_session_id

            return redirect("course.flow.view_flow_page",
                    course_identifier,
                    flow_identifier,
                    0)

        elif ("start_no_credit" in request.POST
                or "start_credit" in request.POST):

            if not allowed_another_session:
                raise PermissionDenied("new session would exceed "
                        "allowed session count limit exceed")

            if have_in_progress_session:
                raise PermissionDenied("cannot start flow when other flow "
                        "is already in progress")

            session = FlowSession()
            session.participation = fctx.participation
            session.active_git_commit_sha = fctx.commit_sha.decode()
            session.flow_id = flow_identifier
            session.in_progress = True
            session.for_credit = "start_credit" in request.POST
            session.save()

            request.session["flow_session_id"] = session.id

            page_count = set_up_flow_session_page_data(fctx.repo, session,
                    fctx.flow_desc, fctx.commit_sha)
            session.page_count = page_count
            session.save()

            return redirect("course.flow.view_flow_page",
                    course_identifier,
                    flow_identifier,
                    0)

        else:
            raise SuspiciousOperation("unrecognized POST action")

    else:
        may_start_credit = (
                not have_in_progress_session
                and allowed_another_session
                and flow_permission.start_credit in fctx.permissions)
        may_start_no_credit = (
                not have_in_progress_session
                and allowed_another_session
                and flow_permission.start_no_credit in fctx.permissions)
        may_review = (
                flow_permission.view_past in fctx.permissions)

        past_sessions = (FlowSession.objects
                .filter(
                    participation=fctx.participation,
                    flow_id=flow_identifier)
                .order_by("start_time"))

        if hasattr(fctx.flow_desc, "grade_aggregation_strategy"):
            from course.models import GRADE_AGGREGATION_STRATEGY_CHOICES
            grade_aggregation_strategy_text = (
                    dict(GRADE_AGGREGATION_STRATEGY_CHOICES)
                    [fctx.flow_desc.grade_aggregation_strategy])
        else:
            grade_aggregation_strategy_text = None

        return render(request, "course/flow-start.html", {
            "participation": fctx.participation,
            "course_desc": fctx.course_desc,
            "course": fctx.course,
            "flow_desc": fctx.flow_desc,
            "grade_aggregation_strategy":
            grade_aggregation_strategy_text,
            "flow_identifier": flow_identifier,

            "may_start_credit": may_start_credit,
            "may_start_no_credit": may_start_no_credit,
            "may_review": may_review,

            "past_sessions": past_sessions,
            "stipulations": fctx.stipulations,
            })

# }}}


# {{{ flow page

class FlowPageContext(FlowContext):
    """This object acts as a container for all the information that a flow page
    may need to render itself or respond to a POST.
    """

    def __init__(self, request, course_identifier, flow_identifier,
            ordinal, flow_session):
        FlowContext.__init__(self, request, course_identifier, flow_identifier,
                flow_session=flow_session)

        from course.models import FlowPageData
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_session=flow_session, ordinal=ordinal)

        from course.content import get_flow_page_desc
        self.page_desc = get_flow_page_desc(
                flow_session, self.flow_desc, page_data.group_id, page_data.page_id)

        self.page = instantiate_flow_page_with_ctx(self, page_data)

        from course.page import PageContext
        self.page_context = PageContext(course=self.course)

        # {{{ dig for previous answers

        previous_answer_visits = (FlowPageVisit.objects
                .filter(flow_session=flow_session)
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
    def percentage(self):
        return int(100*(self.ordinal+1)/self.page_count)

    def create_visit(self):
        page_visit = FlowPageVisit()
        page_visit.flow_session = self.flow_session
        page_visit.page_data = self.page_data
        page_visit.save()


def find_current_flow_session(request, flow_identifier):
    flow_session = None
    flow_session_id = request.session.get("flow_session_id")

    if flow_session_id is not None:
        flow_sessions = list(FlowSession.objects.filter(id=flow_session_id))

        if flow_sessions and flow_sessions[0].flow_id == flow_identifier:
            flow_session, = flow_sessions

    return flow_session


def add_buttons_to_form(fpctx, form):
    from crispy_forms.layout import Submit
    form.helper.add_input(
            Submit("save", "Save answer",
                css_class="col-lg-offset-2"))

    if fpctx.will_receive_feedback():
        form.helper.add_input(Submit("submit", "Submit final answer"))
    else:
        # Only offer 'save and move on' if student will receive no feedback
        if fpctx.page_data.ordinal + 1 < fpctx.flow_session.page_count:
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
    flow_session = find_current_flow_session(request, flow_identifier)

    if flow_session is None:
        messages.add_message(request, messages.WARNING,
                "No in-progress session record found for this flow. "
                "Redirected to flow start page.")

        return redirect("course.flow.start_flow",
                course_identifier,
                flow_identifier)

    fpctx = FlowPageContext(request, course_identifier, flow_identifier,
            ordinal, flow_session)

    page_context = fpctx.page_context
    page_data = fpctx.page_data

    if flow_permission.view not in fpctx.permissions:
        raise PermissionDenied("not allowed to view flow")

    if request.method == "POST":
        if "finish" in request.POST:
            return redirect("course.flow.finish_flow",
                    course_identifier, flow_identifier)
        else:
            # reject if previous answer was final
            if fpctx.prev_answer_is_final:
                raise PermissionDenied("already have final answer")

            # reject answer update if flow is not in-progress
            if not flow_session.in_progress:
                raise PermissionDenied("session is not in progress")

            form, form_html = fpctx.page.post_form(
                    fpctx.page_context, fpctx.page_data.data,
                    post_data=request.POST, files_data=request.POST)

            pressed_button = get_pressed_button(form)

            if form.is_valid():
                # {{{ form validated, process answer

                messages.add_message(request, messages.INFO,
                        "Answer saved.")

                page_visit = FlowPageVisit()
                page_visit.flow_session = fpctx.flow_session
                page_visit.page_data = fpctx.page_data
                page_visit.answer = fpctx.page.answer_data(
                        fpctx.page_context, fpctx.page_data.data,
                        form)
                page_visit.answer_is_final = pressed_button == "submit"
                page_visit.save()

                answer_data = page_visit.answer
                answer_is_final = page_visit.answer_is_final

                if (pressed_button == "save_and_next"
                        and not fpctx.will_receive_feedback()):
                    return redirect("course.flow.view_flow_page",
                            course_identifier,
                            flow_identifier,
                            fpctx.ordinal + 1)
                elif (pressed_button == "save_and_finish"
                        and not fpctx.will_receive_feedback()):
                    return redirect("course.flow.finish_flow",
                            course_identifier, flow_identifier)
                else:
                    # continue at common flow page generation below

                    form, form_html = fpctx.page.make_form(
                            page_context, page_data.data,
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
        answer_is_final = (
                fpctx.prev_answer_is_final

                # can happen if no answer was ever saved
                or not fpctx.flow_session.in_progress)

        if fpctx.page.expects_answer():
            form, form_html = fpctx.page.make_form(
                    page_context, page_data.data,
                    answer_data, answer_is_final)
        else:
            form = None
            form_html = None

    # start common flow page generation

    # defined at this point: form, form_template, answer_data, answer_is_final

    if form is not None and not answer_is_final:
        form = add_buttons_to_form(fpctx, form)

    show_correctness = None
    show_answer = None
    feedback = None

    if fpctx.page.expects_answer() and answer_is_final:
        show_correctness = flow_permission.see_correctness in fpctx.permissions
        show_answer = flow_permission.see_answer in fpctx.permissions

        if show_correctness or show_answer:
            feedback = fpctx.page.grade(
                    page_context, page_data.data, answer_data,
                    # FIXME
                    grade_data=None)

    title = fpctx.page.title(page_context, page_data.data)
    body = fpctx.page.body(page_context, page_data.data)

    # {{{ render flow page

    if form is not None and form_html is None:
        from crispy_forms.utils import render_crispy_form
        from django.template import RequestContext
        context = RequestContext(request, {})
        form_html = render_crispy_form(form, context=context)
        del context

        form_html = '<div class="well">%s</div>' % form_html

    args = {
        "course": fpctx.course,
        "course_desc": fpctx.course_desc,
        "flow_identifier": fpctx.flow_identifier,
        "flow_desc": fpctx.flow_desc,
        "ordinal": fpctx.ordinal,
        "page_data": fpctx.page_data,
        "percentage": fpctx.percentage,
        "flow_session": fpctx.flow_session,
        "participation": fpctx.participation,

        "title": title, "body": body,
        "form_html": form_html,
        "feedback": feedback,
        "show_correctness": show_correctness,
        "show_answer": show_answer,
    }

    if fpctx.page.expects_answer():
        args["max_points"] = fpctx.page.max_points(fpctx.page_data)

    return render(request, "course/flow-page.html", args)

    # }}}

# }}}


# {{{ finish flow

def assemble_answer_visits(flow_session):
    answer_visits = [None] * flow_session.page_count

    from course.models import FlowPageVisit
    answer_page_visits = (FlowPageVisit.objects
            .filter(flow_session=flow_session)
            .filter(answer__isnull=False)
            .order_by("visit_time"))

    for page_visit in answer_page_visits:
        answer_visits[page_visit.page_data.ordinal] = page_visit

    return answer_visits


def count_answered(fctx, answer_visits):
    all_page_data = (FlowPageData.objects
            .filter(flow_session=fctx.flow_session)
            .order_by("ordinal"))

    answered_count = 0
    unanswered_count = 0
    for i, page_data in enumerate(all_page_data):
        assert i == page_data.ordinal

        if answer_visits[i] is not None:
            answer_data = answer_visits[i].answer
        else:
            answer_data = None

        page = instantiate_flow_page_with_ctx(fctx, page_data)
        if page.expects_answer():
            if answer_data is None:
                unanswered_count += 1
            else:
                answered_count += 1

    return (answered_count, unanswered_count)


class GradeInfo(object):
    def __init__(self,
            points, max_points,
            fully_correct_count, partially_correct_count, incorrect_count):
        self.points = points
        self.max_points = max_points
        self.fully_correct_count = fully_correct_count
        self.partially_correct_count = partially_correct_count
        self.incorrect_count = incorrect_count

    def points_percent(self):
        return 100*self.points/self.max_points

    def missed_points_percent(self):
        return 100 - self.points_percent()

    def total_count(self):
        return (self.fully_correct_count
                + self.partially_correct_count
                + self.incorrect_count)

    def fully_correct_percent(self):
        return 100*self.fully_correct_count/self.total_count()

    def partially_correct_percent(self):
        return 100*self.partially_correct_count/self.total_count()

    def incorrect_percent(self):
        return 100*self.incorrect_count/self.total_count()


def gather_grade_info(fctx, answer_visits):
    all_page_data = (FlowPageData.objects
            .filter(flow_session=fctx.flow_session)
            .order_by("ordinal"))

    points = 0
    max_points = 0
    fully_correct_count = 0
    partially_correct_count = 0
    incorrect_count = 0

    for i, page_data in enumerate(all_page_data):
        assert i == page_data.ordinal

        if answer_visits[i] is not None:
            answer_data = answer_visits[i].answer
            grade_data = answer_visits[i].grade_data
        else:
            answer_data = None
            grade_data = None

        page = instantiate_flow_page_with_ctx(fctx, page_data)

        if not page.expects_answer():
            continue

        from course.page import PageContext
        page_context = PageContext(course=fctx.course)

        feedback = page.grade(
                page_context, page_data.data, answer_data, grade_data)

        max_points += page.max_points(page_data.data)
        points += page.max_points(page_data.data)*feedback.correctness

        if feedback.correctness == 1:
            fully_correct_count += 1
        elif feedback.correctness == 0:
            incorrect_count += 1
        else:
            partially_correct_count += 1

    return GradeInfo(
            points=points,
            max_points=max_points,
            fully_correct_count=fully_correct_count,
            partially_correct_count=partially_correct_count,
            incorrect_count=incorrect_count)


@transaction.atomic
def finish_flow(request, course_identifier, flow_identifier):
    flow_session = find_current_flow_session(request, flow_identifier)

    if flow_session is None:
        messages.add_message(request, messages.WARNING,
                "No session record found for this flow. "
                "Redirected to flow start page.")

        return redirect("course.flow.start_flow",
                course_identifier,
                flow_identifier)

    fctx = FlowContext(request, course_identifier, flow_identifier,
            flow_session=flow_session)

    answer_visits = assemble_answer_visits(flow_session)

    from course.content import markdown_to_html

    if request.method == "POST":
        if "submit" not in request.POST:
            raise SuspiciousOperation("odd POST parameters")

        if not flow_session.in_progress:
            raise PermissionDenied("Can't end a session that's already ended")

        # Actually end the flow.

        request.session["flow_session_id"] = None

        grade_info = gather_grade_info(fctx, answer_visits)

        points = grade_info.points
        comment = None

        if hasattr(fctx.stipulations, "credit_percent"):
            comment = "Counted at %.1f%% of %.1f points" % (
                    fctx.stipulations.credit_percent, points)
            points = points * fctx.stipulations.credit_percent / 100

        from django.utils.timezone import now
        flow_session.completion_time = now()
        flow_session.in_progress = False
        flow_session.points = points
        flow_session.max_points = grade_info.max_points
        flow_session.result_comment = comment
        flow_session.save()

        # mark answers as final
        for answer_visit in answer_visits:
            if answer_visit is not None:
                answer_visit.answer_is_final = True
                answer_visit.save()

        from course.models import get_flow_grading_opportunity
        gopp = get_flow_grading_opportunity(
                fctx.course, fctx.flow_identifier, fctx.flow_desc)

        from course.models import grade_state_change_types
        gchange = GradeChange()
        gchange.opportunity = gopp
        gchange.participation = fctx.participation
        gchange.state = grade_state_change_types.graded
        gchange.points = points
        gchange.max_points = grade_info.max_points
        gchange.creator = request.user
        gchange.flow_session = flow_session
        gchange.comment = comment
        gchange.save()

        return render(request, "course/flow-completion-grade.html", {
            "course": fctx.course,
            "course_desc": fctx.course_desc,
            "flow_identifier": fctx.flow_identifier,
            "flow_desc": fctx.flow_desc,
            "body": markdown_to_html(fctx.course, fctx.flow_desc.completion_text),
            "participation": fctx.participation,
            "grade_info": grade_info,
        })

    (answered_count, unanswered_count) = count_answered(fctx, answer_visits)
    if answered_count + unanswered_count == 0:
        # Not serious--no questions in flow. No need to end the flow visit.

        from course.content import markdown_to_html
        return render(request, "course/flow-completion.html", {
            "course": fctx.course,
            "course_desc": fctx.course_desc,
            "flow_identifier": fctx.flow_identifier,
            "flow_desc": fctx.flow_desc,
            "last_page_nr": fctx.page_count-1,
            "body": markdown_to_html(fctx.course, fctx.flow_desc.completion_text),
        })

    elif not flow_session.in_progress:
        # Just reviewing: re-show grades.
        grade_info = gather_grade_info(fctx, answer_visits)

        return render(request, "course/flow-completion-grade.html", {
            "course": fctx.course,
            "course_desc": fctx.course_desc,
            "flow_identifier": fctx.flow_identifier,
            "flow_desc": fctx.flow_desc,
            "body": markdown_to_html(fctx.course, fctx.flow_desc.completion_text),
            "participation": fctx.participation,
            "grade_info": grade_info,
        })

    else:
        # confirm ending flow
        return render(request, "course/flow-confirm-completion.html", {
            "course": fctx.course,
            "course_desc": fctx.course_desc,
            "flow_identifier": fctx.flow_identifier,
            "flow_desc": fctx.flow_desc,
            "last_page_nr": fctx.page_count-1,
            "answered_count": answered_count,
            "unanswered_count": unanswered_count,
            "total_count": answered_count+unanswered_count,
        })

# }}}

# vim: foldmethod=marker
