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


from django.utils.translation import pgettext_lazy, ugettext
# Allow 10x extra credit at the very most.
MAX_EXTRA_CREDIT_FACTOR = 10


COURSE_ID_REGEX = "(?P<course_identifier>[-a-zA-Z0-9]+)"
FLOW_ID_REGEX = "(?P<flow_id>[-_a-zA-Z0-9]+)"


class user_status:  # noqa
    unconfirmed = "unconfirmed"
    active = "active"

USER_STATUS_CHOICES = (
        (user_status.unconfirmed, pgettext_lazy("User status", "Unconfirmed")),
        (user_status.active, pgettext_lazy("User status", "Active")),
        )


class course_status:  # noqa
    open = "open"
    inprogress = "inprogress"
    ended = "ended"

COURSE_STATUS_CHOICES = (
        (course_status.open, pgettext_lazy("Course status", "Open")),
        (course_status.inprogress, pgettext_lazy("Course status", "In_Progress")),
        (course_status.ended, pgettext_lazy("Course status", "Ended")),
        )

class participation_role:  # noqa
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"
    auditor = "auditor"

    # can see analytics
    observer = "observer"

    unenrolled = "unenrolled"


PARTICIPATION_ROLE_CHOICES = (
        (participation_role.instructor,
            pgettext_lazy("Participation role", "Instructor")),
        (participation_role.teaching_assistant,
            pgettext_lazy("Participation role", "Teaching Assistant")),
        (participation_role.student,
            pgettext_lazy("Participation role", "Student")),
        (participation_role.observer,
            pgettext_lazy("Participation role", "Observer")),
        (participation_role.auditor,
            pgettext_lazy("Participation role", "Auditor")),
        # unenrolled is only used internally
        )


class participation_status:  # noqa
    requested = "requested"
    active = "active"
    dropped = "dropped"
    denied = "denied"


PARTICIPATION_STATUS_CHOICES = (
        (participation_status.requested,
            pgettext_lazy("Participation status", "Requested")),
        (participation_status.active,
            pgettext_lazy("Participation status", "Active")),
        (participation_status.dropped,
            pgettext_lazy("Participation status", "Dropped")),
        (participation_status.denied,
            pgettext_lazy("Participation status", "Denied")),
        )


class flow_session_expiration_mode:  # noqa
    """
    .. attribute:: end

        End the session upon expiration. Participants may always choose this mode.

    .. attribute:: roll_over

        Upon expiration, reprocess the session start rules and
        treat the session as if it was started the moment of expiration.
        This may be used to 'roll over' into another set of grading rules,
        say ones assigning less credit for homework turned in late.

        Allowed by :attr:`flow_permission.set_roll_over_expiration_mode`.
    """
    # always allowed
    end = "end"

    # allowed by special permission below
    roll_over = "roll_over"

FLOW_SESSION_EXPIRATION_MODE_CHOICES = (
        (flow_session_expiration_mode.end,
            pgettext_lazy("Flow expiration mode", "End session and grade")),
        (flow_session_expiration_mode.roll_over,
            pgettext_lazy("Flow expiration mode",
                "Keep session and apply new rules")),
        )


def is_expiration_mode_allowed(expmode, permissions):
    if expmode == flow_session_expiration_mode.roll_over:
        if (flow_permission.set_roll_over_expiration_mode
                in permissions):
            return True
    elif expmode == flow_session_expiration_mode.end:
        return True
    else:
        raise ValueError(ugettext("unknown expiration mode"))

    return False


class flow_permission:  # noqa
    """
    .. attribute:: view

        If present, the participant may view flow pages.

    .. attribute:: submit_answer

        If present, the participant may submit answers to prompts provided on
        a flow page.

    .. attribute:: end_session

        If present, the participant may end their flow session and receive an overall
        grade.

    .. attribute:: change_answer

        Grants permission to change an already-graded answer, which may then be
        graded again. Useful for :class:`course.page.PythonCodeQuestion` to
        allow iterative debugging. Requires :attr:`submit_answer` to also be
        present in order to be meaningful. (If a participant may not *submit*
        answers in the first place, the ability to change answers is moot.)

    .. attribute:: see_correctness

        If present, the participant will be shown to what extent their
        submitted answer is correct. (See :attr:`submit_answer`.)

    .. attribute:: see_answer_before_submission

        If present, shows the correct answer to the participant even before they
        have submitted an answer of their own.

    .. attribute:: see_answer_after_submission

        If present, shows the correct answer to the participant after they have
        submitted an answer of their own.

    .. attribute:: set_roll_over_expiration_mode

        Grants permission to let a student choose to let a flow
        "expire" into the then-current set of access rules
        instead of into being submitted for grading.

        See :ref:`flow-life-cycle`.

    """
    view = "view"
    end_session = "end_session"
    submit_answer = "submit_answer"
    change_answer = "change_answer"
    see_correctness = "see_correctness"
    see_answer_before_submission = "see_answer_before_submission"
    see_answer_after_submission = "see_answer_after_submission"
    set_roll_over_expiration_mode = "set_roll_over_expiration_mode"

FLOW_PERMISSION_CHOICES = (
        (flow_permission.view,
            pgettext_lazy("Flow permission", "View the flow")),
        (flow_permission.submit_answer,
            pgettext_lazy("Flow permission", "Submit answers")),
        (flow_permission.end_session,
            pgettext_lazy("Flow permission", "End session")),
        (flow_permission.change_answer,
            pgettext_lazy("Flow permission", "Change already-graded answer")),
        (flow_permission.see_correctness,
            pgettext_lazy("Flow permission",
                "See whether an answer is correct")),
        (flow_permission.see_answer_before_submission,
            pgettext_lazy("Flow permission",
                "See the correct answer before answering")),
        (flow_permission.see_answer_after_submission,
            pgettext_lazy("Flow permission",
                "See the correct answer after answering")),
        (flow_permission.set_roll_over_expiration_mode,
            pgettext_lazy("Flow permission",
                "Set the session to 'roll over' expiration mode")),
        )


class flow_rule_kind:  # noqa
    start = "start"
    access = "access"
    grading = "grading"


FLOW_RULE_KIND_CHOICES = (
        (flow_rule_kind.start,
            pgettext_lazy("Flow rule kind choices", "Session Start")),
        (flow_rule_kind.access,
            pgettext_lazy("Flow rule kind choices", "Session Access")),
        (flow_rule_kind.grading,
            pgettext_lazy("Flow rule kind choices", "Grading")),
        )


class grade_aggregation_strategy:  # noqa
    """A strategy for aggregating multiple grades into one.

    .. attribute:: max_grade

        Use the maximum of the achieved grades for each attempt.

    .. attribute:: avg_grade

        Use the average of the achieved grades for each attempt.

    .. attribute:: min_grade

        Use the minimum of the achieved grades for each attempt.

    .. attribute:: use_earliest

        Use the first of the achieved grades for each attempt.

    .. attribute:: use_latest

        Use the last of the achieved grades for each attempt.
    """

    max_grade = "max_grade"
    avg_grade = "avg_grade"
    min_grade = "min_grade"

    use_earliest = "use_earliest"
    use_latest = "use_latest"


GRADE_AGGREGATION_STRATEGY_CHOICES = (
        (grade_aggregation_strategy.max_grade,
            pgettext_lazy("Grade aggregation strategy", "Use the max grade")),
        (grade_aggregation_strategy.avg_grade,
            pgettext_lazy("Grade aggregation strategy", "Use the avg grade")),
        (grade_aggregation_strategy.min_grade,
            pgettext_lazy("Grade aggregation strategy", "Use the min grade")),
        (grade_aggregation_strategy.use_earliest,
            pgettext_lazy("Grade aggregation strategy", "Use the earliest grade")),
        (grade_aggregation_strategy.use_latest,
            pgettext_lazy("Grade aggregation strategy", "Use the latest grade")),
        )


class grade_state_change_types:  # noqa
    grading_started = "grading_started"
    graded = "graded"
    retrieved = "retrieved"
    unavailable = "unavailable"
    extension = "extension"
    report_sent = "report_sent"
    do_over = "do_over"
    exempt = "exempt"


GRADE_STATE_CHANGE_CHOICES = (
        (grade_state_change_types.grading_started,
            pgettext_lazy("Grade state change", "Grading started")),
        (grade_state_change_types.graded,
            pgettext_lazy("Grade state change", "Graded")),
        (grade_state_change_types.retrieved,
            pgettext_lazy("Grade state change", "Retrieved")),
        (grade_state_change_types.unavailable,
            pgettext_lazy("Grade state change", "Unavailable")),
        (grade_state_change_types.extension,
            pgettext_lazy("Grade state change", "Extension")),
        (grade_state_change_types.report_sent,
            pgettext_lazy("Grade state change", "Report sent")),
        (grade_state_change_types.do_over,
            pgettext_lazy("Grade state change", "Do-over")),
        (grade_state_change_types.exempt,
            pgettext_lazy("Grade state change", "Exempt")),
        )

