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

from course.models import (
        Participation, participation_role, participation_status,
        GradingOpportunity, GradeChange, GradeStateMachine,
        grade_state_change_types)


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
            .order_by("user__last_name", "user__first_name")
            .prefetch_related("user"))

    grade_changes = list(GradeChange.objects
            .order_by(
                "participation__user__last_name",
                "participation__user__first_name",
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
                and (
                    grade_changes[idx].participation.user.last_name.lower(),
                    grade_changes[idx].participation.user.first_name.lower())
                < (
                    participation.user.last_name.lower(),
                    participation.user.first_name.lower())):
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

    return render_course_page(pctx, "course/gradebook.html", {
        "grade_table": zip(participations, grade_table),
        "grading_opportunities": grading_opps,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        })

# }}}


# {{{ grades by grading opportunity

class GradeInfo(object):
    def __init__(self, grade_state_machine, sessions):
        self.grade_state_machine = grade_state_machine
        self.sessions = sessions


@course_view
def view_grades_by_opportunity(pctx, opp_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to view grades")

    opportunity = get_object_or_404(GradingOpportunity, id=int(opp_id))

    if pctx.course != opportunity.course:
        raise SuspiciousOperation("opportunity from wrong course")

    participations = list(Participation.objects
            .filter(
                course=pctx.course,
                status=participation_status.active,
                role=participation_role.student,)
            .order_by("user__last_name", "user__first_name")
            .prefetch_related("user"))

    grade_changes = list(GradeChange.objects
            .filter(opportunity=opportunity)
            .order_by(
                "participation__user__last_name",
                "participation__user__first_name",
                "grade_time")
            .prefetch_related("participation")
            .prefetch_related("participation__user")
            .prefetch_related("opportunity"))

    idx = 0

    grade_table = []
    for participation in participations:
        while (
                idx < len(grade_changes)
                and (
                    grade_changes[idx].participation.user.last_name.lower(),
                    grade_changes[idx].participation.user.first_name.lower())
                < (
                    participation.user.last_name.lower(),
                    participation.user.first_name.lower())):
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

        grade_table.append(
                GradeInfo(
                    participation=participation,
                    opportunity=opp,
                    grade_state_machine=state_machine))

        grade_table.append(grade_row)

    return render_course_page(pctx, "course/gradebook-by-opp.html", {
        "opportunity": opportunity,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        })

# }}}
# vim: foldmethod=marker
