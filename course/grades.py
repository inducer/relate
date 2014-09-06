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
        redirect, get_object_or_404)
from course.utils import course_view, render_course_page
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import connection
from django import forms
from django.db import transaction

from courseflow.utils import StyledForm
from crispy_forms.layout import Submit

from course.models import (
        Participation, participation_role, participation_status,
        GradingOpportunity, GradeChange, GradeStateMachine,
        grade_state_change_types,
        FlowSession)


# {{{ student grade book

@course_view
def view_my_grades(pctx):
    messages.add_message(pctx.request, messages.ERROR,
            "Grade viewing is not yet implemented. (Sorry!) It will be "
            "once you start accumulating a sufficient number of grades.")

    return redirect("course.views.course_page", pctx.course.identifier)

# }}}


# {{{ teacher grade book

@course_view
def view_gradebook(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to view grades")

    # NOTE: It's important that these three queries are sorted consistently,
    # also consistently with the code below.
    grading_opps = list((GradingOpportunity.objects
            .filter(
                course=pctx.course,
                shown_in_grade_book=True,
                )
            .order_by("identifier")))

    participations = list(Participation.objects
            .filter(
                course=pctx.course,
                status=participation_status.active,
                role=participation_role.student,)
            .order_by("id")
            .prefetch_related("user"))

    grade_changes = list(GradeChange.objects
            .filter(
                opportunity__course=pctx.course,
                opportunity__shown_in_grade_book=True)
            .order_by(
                "participation__id",
                "opportunity__identifier",
                "grade_time")
            .prefetch_related("participation")
            .prefetch_related("participation__user")
            .prefetch_related("opportunity"))

    idx = 0

    grade_table = []
    for participation in participations:
        while (
                idx < len(grade_changes)
                and grade_changes[idx].participation.id < participation.id):
            idx += 1

        grade_row = []
        for opp in grading_opps:
            while (
                    idx < len(grade_changes)
                    and grade_changes[idx].participation.pk == participation.pk
                    and grade_changes[idx].opportunity.identifier < opp.identifier
                    ):
                idx += 1

            my_grade_changes = []
            while (
                    idx < len(grade_changes)
                    and grade_changes[idx].opportunity.pk == opp.pk
                    and grade_changes[idx].participation.pk == participation.pk):
                my_grade_changes.append(grade_changes[idx])
                idx += 1

            state_machine = GradeStateMachine()
            state_machine.consume(my_grade_changes)

            grade_row.append(state_machine)

        grade_table.append(grade_row)

    grade_table = sorted(zip(participations, grade_table),
            key=lambda (participation, grades):
                (participation.user.last_name.lower(),
                    participation.user.first_name.lower()))

    return render_course_page(pctx, "course/gradebook.html", {
        "grade_table": grade_table,
        "grading_opportunities": grading_opps,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        })

# }}}


# {{{ grades by grading opportunity

class OpportunityGradeInfo(object):
    def __init__(self, grade_state_machine, flow_sessions):
        self.grade_state_machine = grade_state_machine
        self.flow_sessions = flow_sessions


class EndSessionsForm(StyledForm):
    def __init__(self, rule_ids, *args, **kwargs):
        super(EndSessionsForm, self).__init__(*args, **kwargs)

        self.fields["rule_id"] = forms.ChoiceField(
                choices=tuple(
                    (rule_id, str(rule_id))
                    for rule_id in rule_ids))

        self.helper.add_input(
                Submit("submit", "End sessions and grade",
                    css_class="col-lg-offset-2"))


@transaction.atomic
def end_in_progress_sessions(repo, course, flow_id, rule_id):
    sessions = (FlowSession.objects
            .filter(
                course=course,
                flow_id=flow_id,
                access_rules_id=rule_id,
                in_progress=True,
                ))

    from django.utils.timezone import now
    now_datetime = now()

    for session in sessions:
        assert session.participation is not None

        from course.utils import FlowContext
        from course.flow import finish_flow_session

        fctx = FlowContext(repo, course, flow_id, flow_session=session)

        current_access_rule = fctx.get_current_access_rule(
                session, session.participation.role, session.participation,
                now_datetime)

        finish_flow_session(fctx, session, current_access_rule)


RULE_ID_NONE_STRING = "<<<NONE>>>"


def mangle_rule_id(rule_id):
    if rule_id is None:
        return RULE_ID_NONE_STRING
    else:
        return rule_id


@course_view
def view_grades_by_opportunity(pctx, opp_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to view grades")

    opportunity = get_object_or_404(GradingOpportunity, id=int(opp_id))

    if pctx.course != opportunity.course:
        raise SuspiciousOperation("opportunity from wrong course")

    # {{{ end sessions form

    end_sessions_form = None
    if pctx.role == participation_role.instructor and opportunity.flow_id:
        cursor = connection.cursor()
        cursor.execute("select distinct access_rules_id from course_flowsession "
                "where course_id = %s and flow_id = %s "
                "order by access_rules_id", (pctx.course.id, opportunity.flow_id))
        rule_ids = [mangle_rule_id(row[0]) for row in cursor.fetchall()]

        request = pctx.request
        if request.method == "POST":
            end_sessions_form = EndSessionsForm(
                    rule_ids, request.POST, request.FILES)
            if end_sessions_form.is_valid():
                rule_id = end_sessions_form.cleaned_data["rule_id"]
                if rule_id == RULE_ID_NONE_STRING:
                    rule_id = None
                end_in_progress_sessions(pctx.repo, pctx.course, opportunity.flow_id,
                        rule_id)
        else:
            end_sessions_form = EndSessionsForm(rule_ids)

    # }}}

    # NOTE: It's important that these three queries are sorted consistently,
    # also consistently with the code below.

    participations = list(Participation.objects
            .filter(
                course=pctx.course,
                status=participation_status.active,
                role=participation_role.student,)
            .order_by("id")
            .prefetch_related("user"))

    grade_changes = list(GradeChange.objects
            .filter(opportunity=opportunity)
            .order_by(
                "participation__id",
                "grade_time")
            .prefetch_related("participation")
            .prefetch_related("participation__user")
            .prefetch_related("opportunity"))

    idx = 0

    grade_table = []
    for participation in participations:
        while (
                idx < len(grade_changes)
                and grade_changes[idx].participation.id < participation.id):
            idx += 1

        my_grade_changes = []
        while (
                idx < len(grade_changes)
                and grade_changes[idx].participation.pk == participation.pk):
            my_grade_changes.append(grade_changes[idx])
            idx += 1

        state_machine = GradeStateMachine()
        state_machine.consume(my_grade_changes)

        if opportunity.flow_id:
            flow_sessions = (FlowSession.objects
                    .filter(
                        participation=participation,
                        flow_id=opportunity.flow_id,
                        )
                    .order_by("start_time"))
        else:
            flow_sessions = None

        grade_table.append(
                OpportunityGradeInfo(
                    grade_state_machine=state_machine,
                    flow_sessions=flow_sessions))

    grade_table = sorted(zip(participations, grade_table),
            key=lambda (participation, grades):
                (participation.user.last_name.lower(),
                    participation.user.first_name.lower()))

    return render_course_page(pctx, "course/gradebook-by-opp.html", {
        "opportunity": opportunity,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        "grade_table": grade_table,
        "end_sessions_form": end_sessions_form,
        })

# }}}

# vim: foldmethod=marker
