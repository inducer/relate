from __future__ import annotations


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

import re
from decimal import Decimal
from typing import (  # noqa
    TYPE_CHECKING, Any, Iterable, List, Optional, Text, Tuple, Union, cast,
)

from crispy_forms.layout import Submit
from django import forms, http
from django.contrib import messages  # noqa
from django.core.exceptions import (
    ObjectDoesNotExist, PermissionDenied, SuspiciousOperation,
)
from django.db import connection, transaction
from django.shortcuts import get_object_or_404, redirect, render  # noqa
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy

from course.constants import participation_permission as pperm
from course.flow import adjust_flow_session_page_data
from course.models import (
    FlowPageVisit, FlowSession, GradeChange, GradeStateMachine, GradingOpportunity,
    Participation, grade_state_change_types, participation_status,
)
from course.utils import course_view, render_course_page
from course.views import get_now_or_fake_time
from relate.utils import (
    HTML5DateTimeInput, StyledForm, StyledModelForm, string_concat,
)


# {{{ for mypy

if TYPE_CHECKING:
    from course.content import FlowDesc  # noqa
    from course.models import Course, FlowPageVisitGrade  # noqa
    from course.utils import CoursePageContext  # noqa

# }}}


# {{{ student grade book

@course_view
def view_participant_grades(pctx, participation_id=None):
    if pctx.participation is None:
        raise PermissionDenied(_("must be enrolled to view grades"))

    if participation_id is not None:
        grade_participation = Participation.objects.get(id=int(participation_id))
    else:
        grade_participation = pctx.participation

    is_privileged_view = pctx.has_permission(pperm.view_gradebook)

    if grade_participation != pctx.participation:
        if not is_privileged_view:
            raise PermissionDenied(_("may not view other people's grades"))

    # NOTE: It's important that these two queries are sorted consistently,
    # also consistently with the code below.

    gopp_extra_filter_kwargs = {}
    if not is_privileged_view:
        gopp_extra_filter_kwargs = {"shown_in_participant_grade_book": True}

    grading_opps = list(GradingOpportunity.objects
            .filter(
                course=pctx.course,
                shown_in_grade_book=True,
                **gopp_extra_filter_kwargs
                )
            .order_by("identifier"))

    grade_changes = list(GradeChange.objects
            .filter(
                participation=grade_participation,
                opportunity__pk__in=[gopp.pk for gopp in grading_opps],
                opportunity__shown_in_grade_book=True)
            .order_by(
                "participation__id",
                "opportunity__identifier",
                "grade_time")
            .select_related("participation")
            .select_related("participation__user")
            .select_related("opportunity"))

    idx = 0

    grade_table = []
    for opp in grading_opps:
        if not is_privileged_view:
            if not (opp.shown_in_grade_book
                    and opp.shown_in_participant_grade_book):
                continue
        else:
            if not opp.shown_in_grade_book:
                continue

        while (
                idx < len(grade_changes)
                and grade_changes[idx].opportunity.identifier < opp.identifier
                ):
            idx += 1

        my_grade_changes = []
        while (
                idx < len(grade_changes)
                and grade_changes[idx].opportunity.pk == opp.pk):
            my_grade_changes.append(grade_changes[idx])
            idx += 1

        state_machine = GradeStateMachine()
        state_machine.consume(my_grade_changes)

        grade_table.append(
                GradeInfo(
                    opportunity=opp,
                    grade_state_machine=state_machine))

    return render_course_page(pctx, "course/gradebook-participant.html", {
        "grade_table": grade_table,
        "grade_participation": grade_participation,
        "grading_opportunities": grading_opps,
        "grade_state_change_types": grade_state_change_types,
        "is_privileged_view": is_privileged_view,
        })

# }}}


# {{{ participant list

@course_view
def view_participant_list(pctx):
    if not pctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    participations = list(Participation.objects
            .filter(
                course=pctx.course)
            .order_by("id")
            .select_related("user"))

    return render_course_page(pctx, "course/gradebook-participant-list.html", {
        "participations": participations,
        })

# }}}


# {{{ grading opportunity list

@course_view
def view_grading_opportunity_list(pctx):
    if not pctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    grading_opps = list(GradingOpportunity.objects
            .filter(
                course=pctx.course,
                )
            .order_by("identifier"))

    return render_course_page(pctx, "course/gradebook-opp-list.html", {
        "grading_opps": grading_opps,
        })

# }}}


# {{{ teacher grade book

class GradeInfo:
    def __init__(self, opportunity: GradingOpportunity,
            grade_state_machine: GradeStateMachine) -> None:
        self.opportunity = opportunity
        self.grade_state_machine = grade_state_machine


def get_grade_table(course: Course) -> Tuple[
        List[Participation], List[GradingOpportunity], List[List[GradeInfo]]]:
    # noqa

    # NOTE: It's important that these queries are sorted consistently,
    # also consistently with the code below.
    grading_opps = list(GradingOpportunity.objects
            .filter(
                course=course,
                shown_in_grade_book=True,
                )
            .order_by("identifier"))

    participations = list(Participation.objects
            .filter(
                course=course,
                status=participation_status.active)
            .order_by("id")
            .select_related("user"))

    grade_changes = list(GradeChange.objects
            .filter(
                opportunity__course=course,
                opportunity__shown_in_grade_book=True)
            .order_by(
                "participation__id",
                "opportunity__identifier",
                "grade_time")
            .select_related("participation")
            .select_related("participation__user")
            .select_related("opportunity"))

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

            grade_row.append(
                    GradeInfo(
                        opportunity=opp,
                        grade_state_machine=state_machine))

        grade_table.append(grade_row)

    return participations, grading_opps, grade_table


@course_view
def view_gradebook(pctx):
    if not pctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    participations, grading_opps, grade_table = get_grade_table(pctx.course)

    def grade_key(entry):
        (participation, grades) = entry
        return (participation.user.last_name.lower(),
                    participation.user.first_name.lower())

    grade_table = sorted(zip(participations, grade_table), key=grade_key)

    return render_course_page(pctx, "course/gradebook.html", {
        "grade_table": grade_table,
        "grading_opportunities": grading_opps,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        })


@course_view
def export_gradebook_csv(pctx):
    if not pctx.has_permission(pperm.batch_export_grade):
        raise PermissionDenied(_("may not batch-export grades"))

    participations, grading_opps, grade_table = get_grade_table(pctx.course)

    from io import StringIO
    csvfile = StringIO()

    import csv

    fieldnames = ["user_name", "last_name", "first_name"] + [
            gopp.identifier for gopp in grading_opps]

    writer = csv.writer(csvfile)

    writer.writerow(fieldnames)

    for participation, grades in zip(participations, grade_table):
        writer.writerow([
            participation.user.username,
            participation.user.last_name,
            participation.user.first_name,
            ] + [grade_info.grade_state_machine.stringify_machine_readable_state()
                for grade_info in grades])

    response = http.HttpResponse(
            csvfile.getvalue().encode("utf-8"),
            content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = (
            'attachment; filename="grades-%s.csv"'
            % pctx.course.identifier)
    return response

# }}}


# {{{ grades by grading opportunity

class OpportunitySessionGradeInfo:
    def __init__(self,
                 grade_state_machine,  # Optional[GradeStateMachine]
                 flow_session,  # Optional[FlowSession]
                 flow_id=None,  # Optional[Text]
                 grades=None,  # Optional[Any]
                 has_finished_session=False,  # bool
                 ) -> None:
        """
        :param grade_state_machine: a :class:`GradeStateMachine:` or None.
        :param flow_session: a :class:`FlowSession:` or None.
        :param flow_id: optional, a :class:`str:` or None. This is used to determine
        whether the instance is created by a flow-session-related opportunity.
        :param grades: optional, a :class:`list:` of float or None, representing the
        percentage grades of each page in the flow session.
        :param has_finished_session:  a :class:`bool:`, respresent whether
        the related participation has finished a flow-session, if the opportunity
        is a flow-session related one. This is used to correctly order flow state,
        if the participation has at least one finished flow session, the in-progress
        flow session won't be ordered to top of the session state column.
        """
        self.grade_state_machine = grade_state_machine
        self.flow_session = flow_session
        self.flow_id = flow_id
        self.grades = grades
        self.has_finished_session = has_finished_session


class ModifySessionsForm(StyledForm):
    def __init__(self, session_rule_tags: List[str],
            *args: Any, **kwargs: Any) -> None:

        super().__init__(*args, **kwargs)

        self.fields["rule_tag"] = forms.ChoiceField(
                choices=tuple(
                    (rule_tag, str(rule_tag))
                    for rule_tag in session_rule_tags),
                label=_("Session tag"))
        self.fields["past_due_only"] = forms.BooleanField(
                required=False,
                initial=True,
                help_text=_("Only act on in-progress sessions that are past "
                "their access rule's due date (applies to 'expire')"),
                # Translators: see help text above.
                label=_("Past due only"))

        self.helper.add_input(
                Submit("expire", _("Impose deadline (Expire sessions)")))
        # self.helper.add_input(
        # Submit("end", _("End and grade all sessions")))
        self.helper.add_input(
                Submit("regrade", _("Regrade ended sessions")))
        self.helper.add_input(
                Submit("recalculate", _("Recalculate grades of ended sessions")))


RULE_TAG_NONE_STRING = "<<<NONE>>>"


def mangle_session_access_rule_tag(rule_tag: Optional[str]) -> str:
    if rule_tag is None:
        return RULE_TAG_NONE_STRING
    else:
        return rule_tag


@course_view
def view_grades_by_opportunity(
        pctx: CoursePageContext, opp_id: str) -> http.HttpResponse:

    from course.views import get_now_or_fake_time
    now_datetime = get_now_or_fake_time(pctx.request)

    if not pctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    opportunity = get_object_or_404(GradingOpportunity, id=int(opp_id))

    if pctx.course != opportunity.course:
        raise SuspiciousOperation(_("opportunity from wrong course"))

    # {{{ batch sessions form

    batch_ops_allowed = (
            pctx.has_permission(pperm.batch_impose_flow_session_deadline)
            or pctx.has_permission(pperm.batch_end_flow_session)
            or pctx.has_permission(pperm.batch_regrade_flow_session)
            or pctx.has_permission(pperm.batch_recalculate_flow_session_grade)
            )

    batch_session_ops_form: Optional[ModifySessionsForm] = None
    if batch_ops_allowed and opportunity.flow_id:
        cursor = connection.cursor()
        cursor.execute("select distinct access_rules_tag from course_flowsession "
                "where course_id = %s and flow_id = %s "
                "order by access_rules_tag", (pctx.course.id, opportunity.flow_id))
        session_rule_tags = [
                mangle_session_access_rule_tag(row[0]) for row in cursor.fetchall()]

        request = pctx.request
        if request.method == "POST":
            bsf = batch_session_ops_form = ModifySessionsForm(
                    session_rule_tags, request.POST, request.FILES)

            assert batch_session_ops_form is not None

            if "expire" in request.POST:
                op = "expire"
                if not pctx.has_permission(pperm.batch_impose_flow_session_deadline):
                    raise PermissionDenied(_("may not impose deadline"))

            elif "end" in request.POST:
                op = "end"
                if not pctx.has_permission(pperm.batch_end_flow_session):
                    raise PermissionDenied(_("may not batch-end flows"))

            elif "regrade" in request.POST:
                op = "regrade"
                if not pctx.has_permission(pperm.batch_regrade_flow_session):
                    raise PermissionDenied(_("may not batch-regrade flows"))

            elif "recalculate" in request.POST:
                op = "recalculate"
                if not pctx.has_permission(
                        pperm.batch_recalculate_flow_session_grade):
                    raise PermissionDenied(_("may not batch-recalculate grades"))

            else:
                raise SuspiciousOperation(_("invalid operation"))

            if bsf.is_valid():
                rule_tag = bsf.cleaned_data["rule_tag"]
                past_due_only = bsf.cleaned_data["past_due_only"]

                if rule_tag == RULE_TAG_NONE_STRING:
                    rule_tag = None

                from course.tasks import (
                    expire_in_progress_sessions, finish_in_progress_sessions,
                    recalculate_ended_sessions, regrade_flow_sessions,
                )

                if op == "expire":
                    async_res = expire_in_progress_sessions.delay(
                            pctx.course.id, opportunity.flow_id,
                            rule_tag, now_datetime,
                            past_due_only=past_due_only)

                    return redirect("relate-monitor_task", async_res.id)

                elif op == "end":
                    async_res = finish_in_progress_sessions.delay(
                            pctx.course.id, opportunity.flow_id,
                            rule_tag, now_datetime,
                            past_due_only=past_due_only)

                    return redirect("relate-monitor_task", async_res.id)

                elif op == "regrade":
                    async_res = regrade_flow_sessions.delay(
                            pctx.course.id, opportunity.flow_id,
                            rule_tag, inprog_value=False)

                    return redirect("relate-monitor_task", async_res.id)

                else:
                    assert op == "recalculate"
                    async_res = recalculate_ended_sessions.delay(
                            pctx.course.id, opportunity.flow_id,
                            rule_tag)

                    return redirect("relate-monitor_task", async_res.id)

        else:
            batch_session_ops_form = ModifySessionsForm(session_rule_tags)

    # }}}

    # NOTE: It's important that these queries are sorted consistently,
    # also consistently with the code below.

    participations = list(Participation.objects
            .filter(
                course=pctx.course,
                status=participation_status.active)
            .order_by("id")
            .select_related("user"))

    grade_changes = list(GradeChange.objects
            .filter(opportunity=opportunity)
            .order_by(
                "participation__id",
                "grade_time")
            .select_related("participation")
            .select_related("participation__user")
            .select_related("opportunity"))

    if opportunity.flow_id:
        flow_sessions: Optional[List[FlowSession]] = list(FlowSession.objects
                .filter(
                    flow_id=opportunity.flow_id,
                    )
                .order_by(
                    "participation__id",
                    "start_time"
                    ))
    else:
        flow_sessions = None

    view_page_grades = pctx.request.GET.get("view_page_grades") == "1"

    gchng_idx = 0
    fsess_idx = 0

    finished_sessions = 0
    total_sessions = 0

    grade_table: List[Tuple[Participation, OpportunitySessionGradeInfo]] = []
    for participation in participations:
        # Advance in grade change list
        while (
                gchng_idx < len(grade_changes)
                and grade_changes[gchng_idx].participation.pk < participation.pk):
            gchng_idx += 1

        my_grade_changes = []
        while (
                gchng_idx < len(grade_changes)
                and grade_changes[gchng_idx].participation.pk == participation.pk):
            my_grade_changes.append(grade_changes[gchng_idx])
            gchng_idx += 1

        state_machine = GradeStateMachine()
        state_machine.consume(my_grade_changes)

        # Advance in flow session list
        if flow_sessions is None:
            grade_table.append(
                    (participation, OpportunitySessionGradeInfo(
                        grade_state_machine=state_machine,
                        flow_session=None)))
        else:
            while (
                    fsess_idx < len(flow_sessions)
                    and (
                        flow_sessions[fsess_idx].participation is None
                        or (
                            flow_sessions[fsess_idx].participation.pk
                            < participation.pk))):
                fsess_idx += 1

            my_flow_sessions = []

            while (
                    fsess_idx < len(flow_sessions)
                    and flow_sessions[fsess_idx].participation is not None
                    and (
                        flow_sessions[fsess_idx].participation.pk
                        == participation.pk)):
                my_flow_sessions.append(flow_sessions[fsess_idx])
                fsess_idx += 1

            # When view_page_grades, participations with no started flow sessions
            # should not be included
            if not my_flow_sessions and not view_page_grades:
                grade_table.append(
                        (participation, OpportunitySessionGradeInfo(
                            grade_state_machine=None,
                            flow_id=opportunity.flow_id,
                            flow_session=None)))

            for fsession in my_flow_sessions:
                total_sessions += 1

                assert fsession is not None

                if not fsession.in_progress:
                    finished_sessions += 1

                grade_table.append(
                        (participation, OpportunitySessionGradeInfo(
                            grade_state_machine=state_machine,
                            flow_id=opportunity.flow_id,
                            flow_session=fsession,
                            has_finished_session=bool(finished_sessions))))

    if view_page_grades and len(grade_table) > 0 and opportunity.flow_id is not None:
        # Query grades for flow pages
        all_flow_sessions = [
                cast(FlowSession, info.flow_session)
                for _dummy1, info in grade_table]

        assert all(all_flow_sessions)
        max_page_count = max(fsess.page_count for fsess in all_flow_sessions)
        page_numbers = list(range(1, 1 + max_page_count))

        from course.flow import assemble_page_grades
        page_grades: List[List[Optional[FlowPageVisitGrade]]] = assemble_page_grades(all_flow_sessions)  # noqa

        for (_dummy2, grade_info), grade_list in zip(grade_table, page_grades):  # type: ignore  # noqa
            # Not all pages exist in all sessions
            grades: List[Tuple[Optional[int], Optional[FlowPageVisitGrade]]] = list(enumerate(grade_list))  # noqa
            if len(grades) < max_page_count:
                grades.extend([(None, None)] * (max_page_count - len(grades)))
            grade_info.grades = grades
    else:
        page_numbers = []

    # No need to sort here, datatables resorts anyhow.

    return render_course_page(pctx, "course/gradebook-by-opp.html", {
        "opportunity": opportunity,
        "participations": participations,
        "grade_state_change_types": grade_state_change_types,
        "grade_table": grade_table,
        "batch_session_ops_form": batch_session_ops_form,
        "page_numbers": page_numbers,
        "view_page_grades": view_page_grades,

        "total_sessions": total_sessions,
        "finished_sessions": finished_sessions,
        })

# }}}


# {{{ reopen session UI

NONE_SESSION_TAG = "<<<NONE>>>"  # noqa


class ReopenSessionForm(StyledForm):
    def __init__(self, flow_desc: FlowDesc, current_tag: str,
            *args: Any, **kwargs: Any) -> None:

        super().__init__(*args, **kwargs)

        rules = getattr(flow_desc, "rules", object())
        tags = getattr(rules, "tags", [])

        tags = [NONE_SESSION_TAG] + tags
        self.fields["set_access_rules_tag"] = forms.ChoiceField(
                choices=[(tag, tag) for tag in tags],
                initial=(current_tag
                    if current_tag is not None
                    else NONE_SESSION_TAG),
                label=_("Set access rules tag"))

        self.fields["unsubmit_pages"] = forms.BooleanField(
                initial=True,
                required=False,
                label=_("Re-allow changes to already-submitted questions"))

        self.fields["comment"] = forms.CharField(
                widget=forms.Textarea, required=True,
                label=_("Comment"))

        self.helper.add_input(
                Submit(
                    "reopen", _("Reopen")))


@course_view
@transaction.atomic
def view_reopen_session(pctx: CoursePageContext, flow_session_id: str,
        opportunity_id: str) -> http.HttpResponse:

    if not pctx.has_permission(pperm.reopen_flow_session):
        raise PermissionDenied(_("may not reopen session"))

    request = pctx.request

    session = get_object_or_404(FlowSession, id=int(flow_session_id))

    from course.content import get_flow_desc
    try:
        flow_desc = get_flow_desc(pctx.repo, pctx.course, session.flow_id,
                pctx.course_commit_sha)
    except ObjectDoesNotExist:
        raise http.Http404()

    if request.method == "POST":
        form = ReopenSessionForm(flow_desc, session.access_rules_tag,
            request.POST, request.FILES)

        may_reopen = True
        if session.in_progress:
            messages.add_message(pctx.request, messages.ERROR,
                    _("Cannot reopen a session that's already in progress."))
            may_reopen = False

        if form.is_valid() and may_reopen:
            new_access_rules_tag = form.cleaned_data["set_access_rules_tag"]
            if new_access_rules_tag == NONE_SESSION_TAG:
                new_access_rules_tag = None

            session.access_rules_tag = new_access_rules_tag

            from relate.utils import as_local_time, format_datetime_local, local_now
            now_datetime = local_now()

            session.append_comment(
                    gettext("Session reopened at %(now)s by %(user)s, "
                        "previous completion time was '%(completion_time)s': "
                        "%(comment)s.") % {
                            "now": format_datetime_local(now_datetime),
                            "user": pctx.request.user,
                            "completion_time": format_datetime_local(
                                as_local_time(session.completion_time)),
                            "comment": form.cleaned_data["comment"]
                            })
            session.save()

            from course.flow import reopen_session
            reopen_session(now_datetime, session, suppress_log=True,
                    unsubmit_pages=form.cleaned_data["unsubmit_pages"])

            return redirect("relate-view_single_grade",
                    pctx.course.identifier,
                    session.participation.id,
                    opportunity_id)

    else:
        form = ReopenSessionForm(flow_desc, session.access_rules_tag)

    return render(request, "generic-form.html", {
        "form": form,
        "form_description": _("Reopen session")
        })

# }}}


# {{{ view single grade

def average_grade(opportunity: GradingOpportunity) -> Tuple[Optional[float], int]:

    grade_changes = (GradeChange.objects
            .filter(
                opportunity=opportunity,
                participation__roles__permissions__permission=(
                    pperm.included_in_grade_statistics))
            .order_by(
                "participation__id",
                "grade_time")
            .select_related("participation")
            .select_related("opportunity"))

    grades = []
    my_grade_changes: List[GradeChange] = []

    def finalize() -> None:

        if not my_grade_changes:
            return

        state_machine = GradeStateMachine()
        state_machine.consume(my_grade_changes)

        percentage = state_machine.percentage()
        if percentage is not None:
            grades.append(percentage)

        del my_grade_changes[:]

    last_participation = None
    for gchange in grade_changes:
        if last_participation != gchange.participation:
            finalize()
            last_participation = gchange.participation

        my_grade_changes.append(gchange)

    finalize()

    if grades:
        return sum(grades)/len(grades), len(grades)
    else:
        return None, 0


def get_single_grade_changes_and_state_machine(opportunity: GradingOpportunity,
        participation: Participation) -> Tuple[List[GradeChange], GradeStateMachine]:
    # noqa

    grade_changes = list(
        GradeChange.objects.filter(
            opportunity=opportunity,
            participation=participation)
        .order_by("grade_time")
        .select_related("participation")
        .select_related("participation__user")
        .select_related("creator")
        .select_related("flow_session")
        .select_related("opportunity"))

    state_machine = GradeStateMachine()
    state_machine.consume(grade_changes, set_is_superseded=True)

    return grade_changes, state_machine


@course_view
def view_single_grade(pctx: CoursePageContext, participation_id: str,
        opportunity_id: str) -> http.HttpResponse:

    now_datetime = get_now_or_fake_time(pctx.request)

    participation = get_object_or_404(Participation,
            id=int(participation_id))

    if participation.course != pctx.course:
        raise SuspiciousOperation(_("participation does not match course"))

    opportunity = get_object_or_404(GradingOpportunity, id=int(opportunity_id))

    if pctx.course != opportunity.course:
        raise SuspiciousOperation(_("opportunity from wrong course"))

    my_grade = participation == pctx.participation
    is_privileged_view = pctx.has_permission(pperm.view_gradebook)

    if is_privileged_view:
        if not opportunity.shown_in_grade_book:
            messages.add_message(pctx.request, messages.INFO,
                    _("This grade is not shown in the grade book."))
        if not opportunity.shown_in_participant_grade_book:
            messages.add_message(pctx.request, messages.INFO,
                    _("This grade is not shown in the student grade book."))

    else:
        # unprivileged

        if not my_grade:
            raise PermissionDenied(_("may not view other people's grades"))

        if not (opportunity.shown_in_grade_book
                and opportunity.shown_in_participant_grade_book
                and opportunity.result_shown_in_participant_grade_book
                ):
            raise PermissionDenied(_("grade has not been released"))

    # {{{ modify sessions buttons

    request = pctx.request
    if pctx.request.method == "POST":
        action_re = re.compile("^([a-z]+)_([0-9]+)$")
        action_match = None
        for key in request.POST.keys():
            action_match = action_re.match(key)
            if action_match:
                break

        if not action_match:
            raise SuspiciousOperation(_("unknown action"))

        session = FlowSession.objects.get(id=int(action_match.group(2)))
        op = action_match.group(1)

        adjust_flow_session_page_data(
                pctx.repo, session, pctx.course.identifier,
                respect_preview=False)

        from course.flow import (
            expire_flow_session_standalone, finish_flow_session_standalone,
            recalculate_session_grade, regrade_session,
        )

        try:
            if op == "imposedl":
                if not pctx.has_permission(pperm.impose_flow_session_deadline):
                    raise PermissionDenied()

                expire_flow_session_standalone(
                        pctx.repo, pctx.course, session, now_datetime)
                messages.add_message(pctx.request, messages.SUCCESS,
                        _("Session deadline imposed."))

            elif op == "end":
                if not pctx.has_permission(pperm.end_flow_session):
                    raise PermissionDenied()

                finish_flow_session_standalone(
                        pctx.repo, pctx.course, session,
                        now_datetime=now_datetime)
                messages.add_message(pctx.request, messages.SUCCESS,
                        _("Session ended."))

            elif op == "regrade":
                if not pctx.has_permission(pperm.regrade_flow_session):
                    raise PermissionDenied()

                regrade_session(
                        pctx.repo, pctx.course, session)
                messages.add_message(pctx.request, messages.SUCCESS,
                        _("Session regraded."))

            elif op == "recalculate":
                if not pctx.has_permission(pperm.recalculate_flow_session_grade):
                    raise PermissionDenied()

                recalculate_session_grade(
                        pctx.repo, pctx.course, session)
                messages.add_message(pctx.request, messages.SUCCESS,
                        _("Session grade recalculated."))

            else:
                raise SuspiciousOperation(_("invalid session operation"))

        except KeyboardInterrupt as e:
            messages.add_message(pctx.request, messages.ERROR,
                    string_concat(
                        pgettext_lazy("Starting of Error message",
                            "Error"),
                        ": %(err_type)s %(err_str)s")
                    % {
                        "err_type": type(e).__name__,
                        "err_str": str(e)})

    # }}}

    grade_changes, state_machine = (
        get_single_grade_changes_and_state_machine(opportunity, participation))

    if opportunity.flow_id:
        flow_sessions = list(FlowSession.objects
                .filter(
                    participation=participation,
                    flow_id=opportunity.flow_id,
                    )
                .order_by("start_time"))

        from collections import namedtuple
        SessionProperties = namedtuple(  # noqa
                "SessionProperties",
                ["due", "grade_description"])

        from course.content import get_flow_desc
        from course.utils import get_session_grading_rule

        try:
            flow_desc = get_flow_desc(pctx.repo, pctx.course,
                    opportunity.flow_id, pctx.course_commit_sha)
        except ObjectDoesNotExist:
            flow_sessions_and_session_properties: Optional[List[Tuple[Any, SessionProperties]]] = None  # noqa
        else:
            flow_sessions_and_session_properties = []
            for session in flow_sessions:
                adjust_flow_session_page_data(
                        pctx.repo, session, pctx.course.identifier,
                        flow_desc, respect_preview=False)

                grading_rule = get_session_grading_rule(
                        session, flow_desc, now_datetime)

                session_properties = SessionProperties(
                        due=grading_rule.due,
                        grade_description=grading_rule.description)
                flow_sessions_and_session_properties.append(
                        (session, session_properties))

    else:
        flow_sessions_and_session_properties = None

    avg_grade_percentage, avg_grade_population = average_grade(opportunity)

    show_privileged_info = pctx.has_permission(pperm.view_gradebook)
    show_page_grades = (
            show_privileged_info
            or opportunity.page_scores_in_participant_gradebook)

    # {{{ filter out pre-public grade changes

    if (not show_privileged_info
            and opportunity.hide_superseded_grade_history_before is not None):
        grade_changes = [gchange
                for gchange in grade_changes
                if not gchange.is_superseded
                or gchange.grade_time
                >= opportunity.hide_superseded_grade_history_before]

    # }}}

    return render_course_page(pctx, "course/gradebook-single.html", {
        "opportunity": opportunity,
        "avg_grade_percentage": avg_grade_percentage,
        "avg_grade_population": avg_grade_population,
        "grade_participation": participation,
        "grade_state_change_types": grade_state_change_types,
        "grade_changes": grade_changes,
        "state_machine": state_machine,
        "flow_sessions_and_session_properties": flow_sessions_and_session_properties,
        "show_privileged_info": show_privileged_info,
        "show_page_grades": show_page_grades,
        "allow_session_actions": (
            pperm.impose_flow_session_deadline
            or pperm.end_flow_session
            or pperm.regrade_flow_session
            or pperm.recalculate_flow_session_grade),
        })

# }}}


# {{{ import grades

class ImportGradesForm(StyledForm):
    def __init__(self, course, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["grading_opportunity"] = forms.ModelChoiceField(
            queryset=(GradingOpportunity.objects
                .filter(course=course)
                .order_by("identifier")),
            help_text=_("Click to <a href='%s' target='_blank'>create</a> "
            "a new grading opportunity. Reload this form when done.")
            % reverse("admin:course_gradingopportunity_add"),
            label=pgettext_lazy("Field name in Import grades form",
                                "Grading opportunity"))

        self.fields["attempt_id"] = forms.CharField(
                initial="main",
                required=True,
                label=_("Attempt ID"))
        self.fields["file"] = forms.FileField(
                label=_("File"))

        self.fields["format"] = forms.ChoiceField(
                choices=(
                    ("csvhead", _("CSV with Header")),
                    ("csv", "CSV"),
                    ),
                label=_("Format"))

        self.fields["attr_type"] = forms.ChoiceField(
                choices=(
                    ("email_or_id", _("Email or NetID")),
                    ("institutional_id", _("Institutional ID")),
                    ("username", _("Username")),
                    ),
                label=_("User attribute"))

        self.fields["attr_column"] = forms.IntegerField(
                # Translators: the following strings are for the format
                # informatioin for a CSV file to be imported.
                help_text=_("1-based column index for the user attribute "
                "selected above to locate student record"),
                min_value=1,
                label=_("User attribute column"))
        self.fields["points_column"] = forms.IntegerField(
                help_text=_("1-based column index for the (numerical) grade"),
                min_value=1,
                label=_("Points column"))
        self.fields["feedback_column"] = forms.IntegerField(
                help_text=_("1-based column index for further (textual) feedback"),
                min_value=1, required=False,
                label=_("Feedback column"))
        self.fields["max_points"] = forms.DecimalField(
                initial=100,
                # Translators: "Max point" refers to full credit in points.
                label=_("Max points"))

        self.helper.add_input(Submit("preview", _("Preview")))
        self.helper.add_input(Submit("import", _("Import")))

    def clean(self):
        data = super().clean()
        attempt_id = data.get("attempt_id")
        if attempt_id:
            attempt_id = attempt_id.strip()
            flow_session_specific_attempt_id_prefix = "flow-session-"
            if attempt_id.startswith(flow_session_specific_attempt_id_prefix):
                self.add_error("attempt_id",
                               _('"%s" as a prefix is not allowed')
                               % flow_session_specific_attempt_id_prefix)

        file_contents = data.get("file")
        if file_contents:
            column_idx_list = [
                data["attr_column"],
                data["points_column"],
                data["feedback_column"]
            ]
            has_header = data["format"] == "csvhead"
            header_count = 1 if has_header else 0

            import io

            from course.utils import csv_data_importable
            importable, err_msg = csv_data_importable(
                    io.StringIO(
                        file_contents.read().decode("utf-8", errors="replace")),
                    column_idx_list,
                    header_count)

            if not importable:
                self.add_error("file", err_msg)


class ParticipantNotFound(ValueError):
    pass


def find_participant_from_user_attr(course, attr_type, attr_str):
    attr_str = attr_str.strip()

    exact_mode = "exact"
    if attr_type == "institutional_id":
        exact_mode = "iexact"
    kwargs = {f"user__{attr_type}__{exact_mode}": attr_str}

    matches = (Participation.objects
            .filter(
                course=course,
                status=participation_status.active,
                **kwargs)
            .select_related("user"))

    matches_count = matches.count()
    if not matches_count or matches_count > 1:
        from django.contrib.auth import get_user_model
        from django.utils.encoding import force_str
        attr_verbose_name = force_str(
            get_user_model()._meta.get_field(attr_type).verbose_name)

        map_dict = {"user_attr": attr_verbose_name, "user_attr_str": attr_str}

        if not matches_count:
            raise ParticipantNotFound(
                    _("no participant found with %(user_attr)s "
                    "'%(user_attr_str)s'") % map_dict)
        raise ParticipantNotFound(
                _("more than one participant found with %(user_attr)s "
                "'%(user_attr_str)s'") % map_dict)

    return matches[0]


def find_participant_from_id(course, id_str):
    id_str = id_str.strip().lower()

    matches = (Participation.objects
            .filter(
                course=course,
                status=participation_status.active,
                user__email__istartswith=id_str)
            .select_related("user"))

    surviving_matches = []
    for match in matches:
        if match.user.email.lower() == id_str:
            surviving_matches.append(match)
            continue

        email = match.user.email.lower()
        at_index = email.index("@")
        assert at_index > 0
        uid = email[:at_index]

        if uid == id_str:
            surviving_matches.append(match)
            continue

    if not surviving_matches:
        raise ParticipantNotFound(
                # Translators: use id_string to find user (participant).
                _("no participant found for '%(id_string)s'") % {
                    "id_string": id_str})
    if len(surviving_matches) > 1:
        raise ParticipantNotFound(
                _("more than one participant found for '%(id_string)s'") % {
                    "id_string": id_str})

    return surviving_matches[0]


def fix_decimal(s):
    if "," in s and "." not in s:
        comma_count = len([c for c in s if c == ","])
        if comma_count == 1:
            return s.replace(",", ".")
        else:
            return s

    else:
        return s


def points_equal(num: Optional[Decimal], other: Optional[Decimal]) -> bool:
    if num is None and other is None:
        return True
    if ((num is None and other is not None)
            or (num is not None and other is None)):
        return False
    assert num is not None
    assert other is not None
    return abs(num - other) < 1e-2


def csv_to_grade_changes(
        log_lines,
        course, grading_opportunity, attempt_id, file_contents,
        attr_type, attr_column, points_column, feedback_column,
        max_points, creator, grade_time, has_header,

        # Row count limited to avoid out-of-memory situation.
        # https://github.com/inducer/relate/issues/849
        max_rows=10_000):
    result = []

    import csv

    from course.utils import get_col_contents_or_empty

    gchange_count = 0
    row_count = 0

    for row in csv.reader(file_contents):
        row_count += 1
        if row_count % 30 == 0:
            print(row_count)

        if row_count >= max_rows:
            raise ValueError(_(
                "Too many rows. "
                "Aborted processing after %d rows. "
                "Please split your file into smaller pieces.")
                % max_rows)

        if has_header:
            has_header = False
            continue

        gchange = GradeChange()
        gchange.opportunity = grading_opportunity
        try:
            if attr_type == "email_or_id":
                gchange.participation = find_participant_from_id(
                        course, get_col_contents_or_empty(row, attr_column-1))
            elif attr_type in ["institutional_id", "username"]:
                gchange.participation = find_participant_from_user_attr(
                        course, attr_type,
                        get_col_contents_or_empty(row, attr_column-1))
            else:
                raise NotImplementedError()
        except ParticipantNotFound as e:
            log_lines.append(e)
            continue

        gchange.state = grade_state_change_types.graded
        gchange.attempt_id = attempt_id

        points_str = get_col_contents_or_empty(row, points_column-1).strip()
        # Moodle's "NULL" grades look like this.
        if points_str in ["-", ""]:
            gchange.points = None
        else:
            gchange.points = Decimal(fix_decimal(points_str))

        gchange.max_points = max_points
        if feedback_column is not None:
            gchange.comment = get_col_contents_or_empty(row, feedback_column-1)

        gchange.creator = creator
        gchange.grade_time = grade_time

        last_grades = (GradeChange.objects
                .filter(
                    opportunity=grading_opportunity,
                    participation=gchange.participation,
                    attempt_id=gchange.attempt_id)
                .order_by("-grade_time")[:1])

        if last_grades.count():
            last_grade, = last_grades

            if last_grade.state == grade_state_change_types.graded:
                updated = []
                if not points_equal(last_grade.points, gchange.points):
                    updated.append(gettext("points"))
                if not points_equal(last_grade.max_points, gchange.max_points):
                    updated.append(gettext("max_points"))
                if last_grade.comment != gchange.comment:
                    updated.append(gettext("comment"))

                if updated:
                    log_lines.append(
                            string_concat(
                                "%(participation)s: %(updated)s ",
                                _("updated")
                                ) % {
                                    "participation": gchange.participation,
                                    "updated": ", ".join(updated)})

                    result.append(gchange)
            else:
                result.append(gchange)

        else:
            result.append(gchange)

        gchange_count += 1

    return gchange_count, result


@course_view
@transaction.atomic
def import_grades(pctx):
    if not pctx.has_permission(pperm.batch_import_grade):
        raise PermissionDenied(_("may not batch-import grades"))

    form_text = ""

    log_lines = []

    import io
    request = pctx.request
    if request.method == "POST":
        form = ImportGradesForm(
                pctx.course, request.POST, request.FILES)

        is_import = "import" in request.POST
        if form.is_valid():
            try:
                f = request.FILES["file"]
                f.seek(0)
                data = f.read().decode("utf-8", errors="replace")
                total_count, grade_changes = csv_to_grade_changes(
                        log_lines=log_lines,
                        course=pctx.course,
                        grading_opportunity=form.cleaned_data["grading_opportunity"],
                        attempt_id=form.cleaned_data["attempt_id"],
                        file_contents=io.StringIO(data),
                        attr_type=form.cleaned_data["attr_type"],
                        attr_column=form.cleaned_data["attr_column"],
                        points_column=form.cleaned_data["points_column"],
                        feedback_column=form.cleaned_data["feedback_column"],
                        max_points=form.cleaned_data["max_points"],
                        creator=request.user,
                        grade_time=now(),
                        has_header=form.cleaned_data["format"] == "csvhead")
            except Exception as e:
                messages.add_message(pctx.request, messages.ERROR,
                        string_concat(
                            pgettext_lazy("Starting of Error message",
                                "Error"),
                            ": %(err_type)s %(err_str)s")
                        % {
                            "err_type": type(e).__name__,
                            "err_str": str(e)})
            else:
                if total_count != len(grade_changes):
                    messages.add_message(pctx.request, messages.INFO,
                            _("%(total)d grades found, %(unchaged)d unchanged.")
                            % {"total": total_count,
                               "unchaged": total_count - len(grade_changes)})

                from django.template.loader import render_to_string

                if is_import:
                    GradeChange.objects.bulk_create(grade_changes)
                    form_text = render_to_string(
                            "course/grade-import-preview.html", {
                                "show_grade_changes": False,
                                "log_lines": log_lines,
                                })
                    messages.add_message(pctx.request, messages.SUCCESS,
                            _("%d grades imported.") % len(grade_changes))
                else:
                    form_text = render_to_string(
                            "course/grade-import-preview.html", {
                                "show_grade_changes": True,
                                "grade_changes": grade_changes,
                                "log_lines": log_lines,
                                })

    else:
        form = ImportGradesForm(pctx.course)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form_description": _("Import Grade Data"),
        "form": form,
        "form_text": form_text,
        })

# }}}


# {{{ download all submissions

class DownloadAllSubmissionsForm(StyledForm):
    def __init__(self, page_ids, session_tag_choices, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["page_id"] = forms.ChoiceField(
                choices=tuple(
                    (pid, pid)
                    for pid in page_ids),
                label=_("Page ID"))
        self.fields["which_attempt"] = forms.ChoiceField(
                choices=(
                    ("first", _("Least recent attempt")),
                    ("last", _("Most recent attempt")),
                    ("all", _("All attempts")),
                    ),
                label=_("Attempts to include."),
                help_text=_(
                    "Every submission to the page counts as an attempt."),
                initial="last")
        self.fields["restrict_to_rules_tag"] = forms.ChoiceField(
                choices=session_tag_choices,
                help_text=_("Only download sessions tagged with this rules tag."),
                label=_("Restrict to rules tag"))
        self.fields["non_in_progress_only"] = forms.BooleanField(
                required=False,
                initial=True,
                help_text=_("Only download submissions from non-in-progress "
                    "sessions"),
                label=_("Non-in-progress only"))
        self.fields["include_feedback"] = forms.BooleanField(
                required=False,
                initial=False,
                help_text=_("Include provided feedback as text file in zip"),
                label=_("Include feedback"))
        self.fields["extra_file"] = forms.FileField(
                label=_("Additional File"),
                help_text=_(
                    "If given, the uploaded file will be included "
                    "in the zip archive. "
                    "If the produced archive is to be used for plagiarism "
                    "detection, then this may be used to include the reference "
                    "solution."),
                required=False)

        self.helper.add_input(
                Submit("download", _("Download")))


@course_view
def download_all_submissions(pctx, flow_id):
    if not pctx.has_permission(pperm.batch_download_submission):
        raise PermissionDenied(_("may not batch-download submissions"))

    from course.content import get_flow_desc
    flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_id,
            pctx.course_commit_sha)

    # {{{ find access rules tag

    if hasattr(flow_desc, "rules"):
        access_rules_tags = getattr(flow_desc.rules, "tags", [])
    else:
        access_rules_tags = []

    ALL_SESSION_TAG = string_concat("<<<", _("ALL"), ">>>")  # noqa
    session_tag_choices = [
            (tag, tag)
            for tag in access_rules_tags] + [(ALL_SESSION_TAG,
                    string_concat("(", _("ALL"), ")"))]

    # }}}

    page_ids = [
            f"{group_desc.id}/{page_desc.id}"
            for group_desc in flow_desc.groups
            for page_desc in group_desc.pages]

    from course.page.base import AnswerFeedback

    request = pctx.request
    if request.method == "POST":
        form = DownloadAllSubmissionsForm(page_ids, session_tag_choices,
                request.POST)

        if form.is_valid():
            which_attempt = form.cleaned_data["which_attempt"]

            slash_index = form.cleaned_data["page_id"].index("/")
            group_id = form.cleaned_data["page_id"][:slash_index]
            page_id = form.cleaned_data["page_id"][slash_index+1:]

            from course.utils import PageInstanceCache
            page_cache = PageInstanceCache(pctx.repo, pctx.course, flow_id)

            visits = (FlowPageVisit.objects
                    .filter(
                        flow_session__course=pctx.course,
                        flow_session__flow_id=flow_id,
                        page_data__group_id=group_id,
                        page_data__page_id=page_id,
                        is_submitted_answer=True,
                        )
                    .select_related("flow_session")
                    .select_related("flow_session__participation__user")
                    .select_related("page_data")

                    # We overwrite earlier submissions with later ones
                    # in a dictionary below.
                    .order_by("visit_time"))

            if form.cleaned_data["non_in_progress_only"]:
                visits = visits.filter(flow_session__in_progress=False)

            if form.cleaned_data["restrict_to_rules_tag"] != ALL_SESSION_TAG:
                visits = (visits
                        .filter(
                            flow_session__access_rules_tag=(
                                form.cleaned_data["restrict_to_rules_tag"])))

            submissions = {}

            for visit in visits:
                page = page_cache.get_page(group_id, page_id,
                        pctx.course_commit_sha)

                from course.page import PageContext
                grading_page_context = PageContext(
                        course=pctx.course,
                        repo=pctx.repo,
                        commit_sha=pctx.course_commit_sha,
                        flow_session=visit.flow_session)

                bytes_answer = page.normalized_bytes_answer(
                        grading_page_context, visit.page_data.data,
                        visit.answer)

                if which_attempt in ["first", "last"]:
                    key = (visit.flow_session.participation.user.username,)
                elif which_attempt == "all":
                    key = (visit.flow_session.participation.user.username,
                            str(visit.flow_session.id))
                else:
                    raise NotImplementedError()

                if bytes_answer is not None:
                    if (which_attempt == "first"
                            and key in submissions):
                        # Already there, disregard further ones
                        continue

                    submissions[key] = (
                            bytes_answer, list(visit.grades.all()))

            from io import BytesIO
            from zipfile import ZipFile
            bio = BytesIO()
            with ZipFile(bio, "w") as subm_zip:
                for key, ((extension, bytes_answer), visit_grades) in \
                        submissions.items():
                    basename = "-".join(key)
                    subm_zip.writestr(
                            basename + extension,
                            bytes_answer)

                    if form.cleaned_data["include_feedback"]:
                        feedback_lines = []

                        feedback_lines.append(
                            "scores: %s" % (
                                ", ".join(
                                    str(g.correctness)
                                    for g in visit_grades)))

                        for i, grade in enumerate(visit_grades):
                            feedback_lines.append(75*"-")
                            feedback_lines.append(
                                "grade %i: score: %s" % (i+1, grade.correctness))
                            afb = AnswerFeedback.from_json(grade.feedback, None)
                            if afb is not None:
                                feedback_lines.append(afb.feedback)

                        subm_zip.writestr(
                                basename + "-feedback.txt",
                                "\n".join(feedback_lines))

                extra_file = request.FILES.get("extra_file")
                if extra_file is not None:
                    subm_zip.writestr(extra_file.name, extra_file.read())

            response = http.HttpResponse(
                    bio.getvalue(),
                    content_type="application/zip")
            response["Content-Disposition"] = (
                    'attachment; filename="submissions_%s_%s_%s_%s_%s.zip"'
                    % (pctx.course.identifier, flow_id, group_id, page_id,
                        now().date().strftime("%Y-%m-%d")))
            return response

    else:
        form = DownloadAllSubmissionsForm(page_ids, session_tag_choices)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Download All Submissions in Zip file")
        })

# }}}


# {{{ edit_grading_opportunity

class EditGradingOpportunityForm(StyledModelForm):
    def __init__(self, add_new: bool, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        if not add_new:
            self.fields["identifier"].disabled = True

        self.fields["course"].disabled = True
        self.fields["flow_id"].disabled = True
        self.fields["creation_time"].disabled = True

        self.helper.add_input(
                Submit("submit", _("Update")))

    class Meta:
        model = GradingOpportunity
        exclude = (
                # do not exclude 'course', used in unique_together checking
                # not used
                "due_time",
                )
        widgets = {
                "hide_superseded_grade_history_before": HTML5DateTimeInput(),
                }


@course_view
def edit_grading_opportunity(pctx: CoursePageContext,
        opportunity_id: int) -> http.HttpResponse:
    if not pctx.has_permission(pperm.edit_grading_opportunity):
        raise PermissionDenied()

    request = pctx.request

    num_opportunity_id = int(opportunity_id)
    if num_opportunity_id == -1:
        gopp = GradingOpportunity(course=pctx.course)
        add_new = True
    else:
        gopp = get_object_or_404(GradingOpportunity, id=num_opportunity_id)
        add_new = False

    if gopp.course.id != pctx.course.id:
        raise SuspiciousOperation(
                "may not edit grading opportunity in different course")

    if request.method == "POST":
        form = EditGradingOpportunityForm(add_new, request.POST, instance=gopp)

        if form.is_valid():
            form.save()
            return redirect("relate-edit_grading_opportunity",
                    pctx.course.identifier, form.instance.id)

    else:
        form = EditGradingOpportunityForm(add_new, instance=gopp)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form_description": _("Edit Grading Opportunity"),
        "form": form
        })

# }}}

# vim: foldmethod=marker
