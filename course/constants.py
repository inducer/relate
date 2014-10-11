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


class user_status:
    unconfirmed = "unconfirmed"
    active = "active"

USER_STATUS_CHOICES = (
        (user_status.unconfirmed, "Unconfirmed"),
        (user_status.active, "Active"),
        )


class participation_role:
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"

    # can see analytics
    observer = "observer"

    unenrolled = "unenrolled"


PARTICIPATION_ROLE_CHOICES = (
        (participation_role.instructor, "Instructor"),
        (participation_role.teaching_assistant, "Teaching Assistant"),
        (participation_role.student, "Student"),
        (participation_role.observer, "Observer"),
        # unenrolled is only used internally
        )


class participation_status:
    requested = "requested"
    active = "active"
    dropped = "dropped"
    denied = "denied"


PARTICIPATION_STATUS_CHOICES = (
        (participation_status.requested, "Requested"),
        (participation_status.active, "Active"),
        (participation_status.dropped, "Dropped"),
        (participation_status.denied, "Denied"),
        )


class flow_session_expriration_mode:
    end = "end"
    roll_over = "roll_over"

FLOW_SESSION_EXPIRATION_MODE_CHOICES = (
        (flow_session_expriration_mode.end, "End session and grade"),
        (flow_session_expriration_mode.roll_over, "Roll over to new rules"),
        )


def is_expiration_mode_allowed(expmode, permissions):
    if expmode == flow_session_expriration_mode.roll_over:
        if (flow_permission.set_roll_over_expiration_mode
                in permissions):
            return True
    elif expmode == flow_session_expriration_mode.end:
        return True
    else:
        raise ValueError("unknown expiration mode")

    return False


class flow_permission:
    view = "view"
    view_past = "view_past"
    start_credit = "start_credit"
    start_no_credit = "start_no_credit"

    change_answer = "change_answer"
    see_correctness = "see_correctness"
    see_correctness_after_completion = "see_correctness_after_completion"
    see_answer = "see_answer"
    see_answer_after_completion = "see_answer_after_completion"
    set_roll_over_expiration_mode = "set_roll_over_expiration_mode"

FLOW_PERMISSION_CHOICES = (
        (flow_permission.view, "View the flow"),
        (flow_permission.view_past, "Review past attempts"),
        (flow_permission.start_credit, "Start a for-credit session"),
        (flow_permission.start_no_credit, "Start a not-for-credit session"),

        (flow_permission.change_answer, "Change already-graded answer"),
        (flow_permission.see_correctness, "See whether an answer is correct"),
        (flow_permission.see_correctness_after_completion,
            "See whether an answer is correct after completing the flow"),
        (flow_permission.see_answer, "See the correct answer"),
        (flow_permission.see_answer_after_completion,
            "See the correct answer after completing the flow"),
        (flow_permission.set_roll_over_expiration_mode,
            "Set the session to 'roll over' expiration mode"),
        )


class grade_aggregation_strategy:
    max_grade = "max_grade"
    avg_grade = "avg_grade"
    min_grade = "min_grade"

    use_earliest = "use_earliest"
    use_latest = "use_latest"


GRADE_AGGREGATION_STRATEGY_CHOICES = (
        (grade_aggregation_strategy.max_grade, "Use the max grade"),
        (grade_aggregation_strategy.avg_grade, "Use the avg grade"),
        (grade_aggregation_strategy.min_grade, "Use the min grade"),

        (grade_aggregation_strategy.use_earliest, "Use the earliest grade"),
        (grade_aggregation_strategy.use_latest, "Use the latest grade"),
        )


class grade_state_change_types:
    grading_started = "grading_started"
    graded = "graded"
    retrieved = "retrieved"
    unavailable = "unavailable"
    extension = "extension"
    report_sent = "report_sent"
    do_over = "do_over"
    exempt = "exempt"


GRADE_STATE_CHANGE_CHOICES = (
        (grade_state_change_types.grading_started, 'Grading started'),
        (grade_state_change_types.graded, 'Graded'),
        (grade_state_change_types.retrieved, 'Retrieved'),
        (grade_state_change_types.unavailable, 'Unavailable'),
        (grade_state_change_types.extension, 'Extension'),
        (grade_state_change_types.report_sent, 'Report sent'),
        (grade_state_change_types.do_over, 'Do-over'),
        (grade_state_change_types.exempt, 'Exempt'),
        )
