Flows
=====

.. currentmodule:: course.constants

All interactive content in RELATE is part of a *flow*. Relate uses the made-up
word "flow" to denote an interactive experience that can be any of the
following:

* A quiz
* A few pages of introductory text, combined with some videos
* An exam
* A long-form homework assignment

And possibly many more different things. Technically, a flow consists of
multiple webpages, each of which may allow the participant some type of
interaction, such as submitting answers to questions. All interactions of the
participant with a flow constitute a session. A participant may have multiple
sessions per flow, corresponding to, for example, being able to take the same
quiz multiple times.

This chapter describes how flows are defined from the instructor's perspective.
This consists of two main parts. The first part is defining the interactions
themselves, by providing content for the flow pages. The second consists of
describing what participants are allowed to do, and what grades they are to
receive for their interactions. The system allows tremendous latitude in
defining these rules.

Things that can be decided by flow rules include the following:

* Is student allowed only one or multiple sessions?
* Is the student allowed to review past sessions?
* What are the deadlines involved and how much credit is received for completing a flow?
* Is a participant shown the correct answer and/or the correctness of their
  answer? When are they shown this information? (Right after they submit their
  answer or only after the deadline passes or perhaps right after they have
  submitted their work for grading?)

An Example
----------

.. code-block:: yaml

    title: "RELATE Test Quiz"
    description: |

        # RELATE Test Quiz

    rules:
        # (Things behind '#' hash marks are comments.)
        # Allow students to start two attempts at the quiz before the deadline.
        # After that, only allow access to previously started quizzes.

        start:
        -
            if_after: 2015-03-06 23:59:00
            if_has_role: [student, ta, instructor]
            if_has_fewer_sessions_than: 2
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            may_start_new_session: False
            may_list_existing_sessions: True

        # Allow students to submit quiz answers before the deadline.
        # After the deadline, the quiz becomes read-only. (The 'modify'
        # permission goes away.)

        access:
        -
            if_after: 2015-03-06 23:59:02
            permissions: [view, submit_answer, end_session, see_correctness]

        -
            permissions: [view, see_correctness, see_answer_after_submission]

        # Record grades under the machine-readable name 'test_quiz'.
        # If there is more than one grade, use the maximum.

        grade_identifier: test_quiz
        grade_aggregation_strategy: max_grade

        grading:
        -   credit_percent: 100

    pages:

    -
        type: Page
        id: welcome
        content: |

            # Welcome to the test quiz for RELATE!

            Don't be scared.

    -
        type: ChoiceQuestion
        id: color
        prompt: |

            # Colors

            What color is the sun?

        choices:

        - Blue
        - Green
        - ~CORRECT~ Yellow

    completion_text: |

        # See you in class!

        Thanks for completing the quiz.

Overall Structure of a Flow
---------------------------

When described in YAML, a flow has the following components:

.. class:: Flow

    .. attribute:: title

        A plain-text title of the flow

    .. attribute:: description

        A description in :ref:`markup` shown on the start page of the flow.

    .. attribute:: completion_text

        (Optional) Some text in :ref:`markup` shown once a student has
        completed the flow.

    .. attribute:: notify_on_submit

        (Optional) A list of email addresses which to notify about a flow submission by
        a participant.

    .. attribute:: rules

        (Optional) Some rules governing students' use and grading of the flow.
        See :ref:`flow-rules`.

    .. attribute:: groups

        A list of :class:`FlowPageGroup`.  Exactly one of
        :attr:`groups` or :class:`pages` must be given.

    .. attribute:: pages

        A list of :ref:`pages <flow-page>`. If you specify this, a single
        :class:`FlowPageGroup` will be implicitly created. Exactly one of
        :attr:`groups` or :class:`pages` must be given.

.. _flow-rules:

Flow rules
----------

An Example
^^^^^^^^^^

Here's a commented example:

.. code-block:: yaml

    rules:
        # Rules that govern when a new session may be started and whether
        # existing sessions may be listed.

        start:
        -
            # Members of the listed roles may start a new session of this
            # flow if they have fewer than 2 existing sessions if the current
            # time is before the event 'end_week 1'.

            if_before: end_week 1
            if_has_role: [student, ta, instructor]
            if_has_fewer_sessions_than: 2
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            # Otherwise, no new sessions will be allowed,
            # but existing ones may be listed.

            may_start_new_session: False
            may_list_existing_sessions: True

        # Rules that govern what a user may do with an existing session.
        access:
        -
             # Before the event 'end_week 2', a user may view, submit answers
             # to the flow, and see the grade they received for their answers.

             if_before: end_week 2
             permissions: [view, modify, see_correctness]

        -
             # Afterwards, they will also be allowed to see the correct answer.
             permissions: [view, modify, see_correctness, see_answer_after_submission]

        # Rules that govern how (permanent) grades are generated from the
        # results of a flow.

        # Grades for this flow are recorded under grade identifier 'la_quiz'.
        # Multiple such grades (if present) are aggregated by taking their maximum.

        grade_identifier: la_quiz
        grade_aggregation_strategy: max_grade

        grading:
        -
            # If the user completes the flow before the event 'end_week 1', they
            # receive full credit.

            if_completed_before: end_week 1
            credit_percent: 100

        -
            # Otherwise, no credit is given.
            credit_percent: 0

Overall structure
^^^^^^^^^^^^^^^^^

.. class:: FlowRules

    Found in the ``rules`` attribute of a :class:`Flow`.

    .. attribute:: start

        Rules that govern when a new session may be started and whether
        existing sessions may be listed.

        A list of :class:`FlowStartRules`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. attribute:: access

        Rules that govern what a user may do while they are interacting with an
        existing session.

        A list of :class:`FlowAccessRules`.

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. rubric:: Grading-Related

    .. attribute:: grade_identifier

        (Required) The identifier of the grade to be generated once the
        participant completes the flow.  If ``null``, no grade is generated.

    .. attribute:: grade_aggregation_strategy

        (Required if :attr:`grade_identifier` is not ``null``)

        One of :class:`grade_aggregation_strategy`.

    .. attribute:: grading

        Rules that govern how (permanent) overall grades are generated from the
        results of a flow. These rules apply once a flow session ends/is submitted
        for grading. See :ref:`flow-life-cycle`.

        (Required if grade_identifier is not ``null``)
        A list of :class:`FlowGradingRules`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

Rules for starting new sessions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. class:: FlowStartRules

    Rules that govern when a new session may be started and whether
    existing sessions may be listed.

    Found in the ``start`` attribute of :class:`FlowRules`.

    .. rubric:: Conditions

    .. attribute:: if_after

        (Optional) A :ref:`datespec <datespec>` that determines a date/time after which this rule
        applies.

    .. attribute:: if_before

        (Optional) A :ref:`datespec <datespec>` that determines a date/time before which this rule
        applies.

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) restricting flow starting based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: if_has_in_progress_session

        (Optional) A Boolean (True/False) value, indicating that the rule only applies
        if the participant has an in-progress session.

    .. attribute:: if_has_session_tagged

        (Optional) An identifier (or ``null``) indicating that the rule only applies
        if the participant has a session with the corresponding tag.

    .. attribute:: if_has_fewer_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer than this
        number of sessions.

    .. attribute:: if_has_fewer_tagged_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer than this
        number of sessions with access rule tags.

    .. attribute:: if_signed_in_with_matching_exam_ticket

        (Optional) The rule applies if the participant signed in with an exam
        ticket matching this flow.

    .. rubric:: Rules specified

    .. attribute:: may_start_new_session

        (Mandatory) A Boolean (True/False) value indicating whether, if the rule applies,
        the participant may start a new session.

    .. attribute:: may_list_existing_sessions

        (Mandatory) A Boolean (True/False) value indicating whether, if the rule applies,
        the participant may view a list of existing sessions.

    .. attribute:: tag_session

        (Optional) An identifier that will be applied to a newly-created session as a "tag".
        This can be used by :attr:`FlowAccessRules.if_has_tag` and
        :attr:`FlowGradingRules.if_has_tag`.

    .. attribute:: default_expiration_mode

        (Optional) One of :class:`flow_session_expiration_mode`. The expiration mode applied
        when a session is first created or rolled over.

Rules about accessing and interacting with a flow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. class:: FlowAccessRules

    Rules that govern what a user may do with an existing session.

    Found in the ``access`` attribute of :class:`FlowRules`.

    .. rubric:: Conditions

    .. attribute:: if_after

        (Optional) A :ref:`datespec <datespec>` that determines a date/time after which this rule
        applies.

    .. attribute:: if_before

        (Optional) A :ref:`datespec <datespec>` that determines a date/time before which this rule
        applies.

    .. attribute:: if_started_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session was started before
        this time.

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) restricting flow access based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: if_has_tag

        (Optional) Rule applies if session has this tag (see :attr:`FlowStartRules.tag_session`),
        an identifier.

    .. attribute:: if_in_progress

        (Optional) A Boolean (True/False) value. Rule applies if the session's
        in-progress status matches this Boolean value.

    .. attribute:: if_completed_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session was completed before
        this time.

    .. attribute:: if_expiration_mode

        (Optional) One of :class:`flow_session_expiration_mode`. Rule applies if the expiration mode
        (see :ref:`flow-life-cycle`) matches.

    .. attribute:: if_session_duration_shorter_than_minutes

        (Optional) The rule applies if the current session has been going on for
        less than the specified number of minutes. Fractional values (e.g. "0.5")
        are accepted here.

    .. attribute:: if_signed_in_with_matching_exam_ticket

        (Optional) The rule applies if the participant signed in with an exam
        ticket matching this flow.

    .. rubric:: Rules specified

    .. attribute:: permissions

        A list of :class:`flow_permission`.

        :attr:`flow_permission.submit_answer` and :attr:`flow_permission.end_session`
        are automatically removed from a finished (i.e. not 'in-progress')
        session.

    .. attribute:: message

        (Optional) Some text in :ref:`markup` that is shown to the student in an 'alert'
        box at the top of the page if this rule applies.

.. _flow-permissions:

Access permission bits
~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: flow_permission

Determining how final (overall) grades of flows are computed
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. class:: FlowGradingRules

    Rules that govern how (permanent) grades are generated from the
    results of a flow.

    Found in the ``grading`` attribute of :class:`FlowRules`.

    .. rubric:: Conditions

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_started_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session was started before
        this time.

    .. attribute:: if_has_tag

        (Optional) Rule applies if session has this tag (see :attr:`FlowStartRules.tag_session`),
        an identifier.

    .. attribute:: if_completed_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session was completed before
        this time.

    .. rubric:: Rules specified

    .. attribute:: credit_percent

        (Optional) A number indicating the percentage of credit assigned for this flow.
        Defaults to 100 if not present.

    .. attribute:: due

        A :ref:`datespec <datespec>` indicating the due date of the flow. This is shown to the
        participant and also used to batch-expire 'past-due' flows.

    .. attribute:: generates_grade

        (Optional) A Boolean indicating whether a grade will be recorded when this
        flow is ended. Note that the value of this rule must never change over
        the lifetime of a flow. I.e. a flow that, at some point during its lifetime,
        *may* have been set to generate a grade must *always* be set to generate
        a grade. Defaults to ``true``.

    .. attribute:: use_last_activity_as_completion_time

        (Optional) A Boolean indicating whether the last time a participant made
        a change to their flow should be used as the completion time.

        Defaults to ``false`` to match past behavior. ``true`` is probably the more
        sensible value for this.

    .. attribute:: description

        (Optional) A description of this set of grading rules being applied to the flow.
        Shown to the participant on the flow start page.

    .. attribute:: max_points

        (Optional, an integer or floating point number if given)
        The number of points on the flow which constitute
        "100% of the achievable points". If not given, this is automatically
        computed by summing point values from all constituent pages.

        This may be used to 'grade out of N points', where N is a number that
        is lower than the actually achievable count.

    .. attribute:: max_points_enforced_cap

        (Optional, an integer or floating point number if given)
        No participant will have a grade higher than this recorded for this flow.
        This may be used to limit the amount of 'extra credit' achieved beyond
        :attr:`max_points`.

    .. attribute:: bonus_points

        (Optional, an integer or floating point number if given)
        This number of points will be added to every participant's score.

.. autoclass:: grade_aggregation_strategy

.. _flow-page:

Flow pages
----------

.. _flow-groups:

Grouping
^^^^^^^^

Each flow consists of a number of page groups, each of which is made up of
individual :ref:`flow-page`.

The purpose of page groups is to allow shuffling and random selection of
some subset of pages. For example, this functionality would allow you to
have a flow consisting of:

* a fixed introduction page (that is always at the beginning)

* a group of exam questions randomly selected from a bigger pool

* a fixed final page (that may ask the student to, say, affirm academic
  honesty)

Each of these would be a separate 'group'.

Each group allows the following attributes:

.. class:: FlowPageGroup

    .. attribute:: id

        (Required) A symbolic name for the page group.

    .. attribute:: pages

        (Required) A list of :ref:`flow-page`

    .. attribute:: shuffle

        (Optional) A boolean (True/False) indicating whether the order
        of pages should be as in the list :attr:`FlowGroup.pages` or
        determined by random shuffling

    .. attribute:: max_page_count

        (Optional) An integer limiting the page count of this group
        to a certain value. Allows selection of a random subset by combining
        with :attr:`FlowGroup.shuffle`.

.. _page-permissions:

Per-page permissions
^^^^^^^^^^^^^^^^^^^^

The granted access permissions for the entire flow (see
:class:`FlowAccessRules`) can be modified on a per-page basis.  This happens in
the ``access_rules`` sub-block of each page,
e.g. in :attr:`course.page.ChoiceQuestion.access_rules`:

.. class:: PageAccessRules

    .. attribute:: add_permissions

        A list of :class:`flow_permission` values that are granted *in addition* to
        the globally granted ones.

    .. attribute:: remove_permissions

        A list of :class:`flow_permission` values that are not granted for this page
        even if they are granted by the global flow permissions.

For example, to grant permission to revise an answer on a
:class:`course.page.PythonCodeQuestion`, one might type::

    type: PythonCodeQuestion
    id: addition
    access_rules:
        add_permissions:
            - change_answer
    value: 1

Predefined Page Types
---------------------

.. currentmodule:: course.page

The following page types are predefined:

* :class:`Page` -- a page of static text
* :class:`TextQuestion` -- a page allowing a textual answer
* :class:`SurveyTextQuestion` -- a page allowing an ungraded textual answer
* :class:`HumanGradedTextQuestion` -- a page allowing an textual answer graded by a human
* :class:`InlineMultiQuestion` -- a page allowing answers to be given in-line of a block of text
* :class:`ChoiceQuestion` -- a one-of-multiple-choice question
* :class:`MultipleChoiceQuestion` -- a many-of-multiple-choice question
* :class:`SurveyChoiceQuestion` -- a page allowing an ungraded multiple-choice answer
* :class:`PythonCodeQuestion` -- an autograded code question
* :class:`PythonCodeQuestionWithHumanTextFeedback`
  -- a code question with automatic *and* human grading
* :class:`FileUploadQuestion`
  -- a question allowing a file upload and human grading

.. warning::

    If you change the type of a question, you *must* also change its ID.
    Otherwise, RELATE will assume that existing answer data for this
    question applies to the new question type, and will likely get very
    confused, for one because the answer data found will not be of the
    expected type.

.. |id-page-attr| replace::

    A short identifying name, unique within the page group. Alphanumeric
    with dashes and underscores, no spaces.

.. |title-page-attr| replace::

    The page's title, a string. No markup allowed. Required. If not supplied,
    the first ten lines of the page body are searched for a
    Markdown heading (``# My title``) and this heading is used as a title.

.. |access-rules-page-attr| replace::

    Optional. See :ref:`page-permissions`.

.. |value-page-attr| replace::

    An integer or a floating point number, representing the
    point value of the question.

.. |is-optional-page-attr| replace::

    Optional. A Boolean value indicating whether the page is an optional page
    which does not require answer for fully completion of the flow.
    If ``true``, :attr:`value` should not present. Defaults to ``false`` if not present.
    Note that ``is_optional_page: true`` differs from ``value: 0`` in that finishing flows
    with unanswered page(s) with the latter will be warned of "unanswered question(s)",
    while with the former won't. When using not-for-grading page(s) to collect
    answers from students, it's to better use ``value: 0``.

.. |text-widget-page-attr| replace::

    Optional.
    One of ``text_input`` (default), ``textarea``, ``editor:MODE``
    (where ``MODE`` is a valid language mode for the CodeMirror editor,
    e.g. ``yaml``, or ``python`` or ``markdown``)

Show a Page of Text/HTML (Ungraded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: Page()

Fill-in-the-Blank (Automatically Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: TextQuestion()

Free-Answer Survey (Ungraded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: SurveyTextQuestion()

Fill-in-the-Blank (long-/short-form) (Human-graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: HumanGradedTextQuestion()

Fill-in-Multiple-Blanks (Automatically Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: InlineMultiQuestion()

One-out-of-Many Choice (Automatically Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: ChoiceQuestion()

Many-out-of-Many Choice (Automatically Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: MultipleChoiceQuestion()

One-out-of-Many Survey (Ungraded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: SurveyChoiceQuestion()

Write Python Code (Automatically Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: PythonCodeQuestion()

Write Python Code (Automatically and Human-Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: PythonCodeQuestionWithHumanTextFeedback()

Upload a File (Human-Graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: FileUploadQuestion()

Definining your own page types
------------------------------

.. autoclass:: PageContext
.. autoclass:: PageBehavior
.. autofunction:: get_auto_feedback
.. autoclass:: AnswerFeedback
.. autoclass:: PageBase

.. currentmodule:: course.page.base
.. autoclass:: PageBaseWithTitle
.. autoclass:: PageBaseWithHumanTextFeedback
.. autoclass:: PageBaseWithCorrectAnswer

.. _flow-life-cycle:

Life cycle
----------

.. currentmodule:: course.constants

.. autoclass:: flow_session_expiration_mode

Sample Rule Sets
----------------

RELATE's rule system is quite flexible and allows many different styles
of interaction. Some of what's possible may not be readily apparent
from the reference documentation above, so the following examples
serve to illustrate the possibilities.

Simple Single-Submission Assignment with a Due Date
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The rules for this can be written as follows::

    title: "An assignment"
    description: |

        # An Assignment

    rules:
        start:
        -
            if_before: my_assignment_due
            if_has_role: [student, ta, instructor]
            if_has_fewer_sessions_than: 1
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            may_start_new_session: False
            may_list_existing_sessions: True

        access:
        -
            # 'modify'-type permissions are automatically removed at
            # session end. Add the following if desired:
            #
            # see_correctness
            # change_answer
            #
            permissions: [view, submit_answer, end_session]

        grade_identifier: "my_assignment"
        grade_aggregation_strategy: max_grade

        grading:
        -
            credit_percent: 100
            due: my_assignment_due
            description: "Full credit"

    pages:

    -   ....

Exam
^^^^

This rule set describes the following:

* An exam that can be taken at most once in a specified facility.
* Instructors can preview and take the exam from anywhere, at any time,
  as many times as needed.
* No feedback on correctness is provided during the exam.

The rules for this can be written as follows::

    title: "Midterm exam 1"
    description: |
        # Midterm exam 1

    rules:
        grade_identifier: exam_1
        grade_aggregation_strategy: use_earliest

        start:
        -
            if_has_role: [instructor]
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            if_in_facility: "cbtf"
            if_has_role: [student, instructor]
            if_has_fewer_sessions_than: 1
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            if_in_facility: "cbtf"
            if_has_role: [student, instructor]
            may_start_new_session: False
            may_list_existing_sessions: True

        -
            may_start_new_session: False
            may_list_existing_sessions: False

        access:
        -
            if_after: end_of_class
            if_has_role: [unenrolled, student]
            permissions: []

        -
            if_in_facility: "cbtf"
            if_has_role: [student, instructor]
            if_after: exam 1 - 1 week
            if_before: end:exam 1 + 2 weeks
            permissions: [view, submit_answer, end_sesion, cannot_see_flow_result, lock_down_as_exam_session]

        -
            if_has_role: [instructor]
            permissions: [view, submit_answer, end_sesion, cannot_see_flow_result, lock_down_as_exam_session]

        -
            permissions: []

        grading:
        -   generates_grade: true

    pages:

    -   ....


Pre-Lecture Quiz with Multiple Attempts and Practice Sessions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This rule set describes the following:

* A quiz is due at the start of a lecture.
* After that deadline, the quiz remains available to take
  for half-credit for a week.
* After that week, the quiz will remain available for practice,
  but no attempt will be counted for credit.
* Three for-credit attempts are allowed. Any attempts beyond
  that are simply for practice and not counted for credit.
* Visitors/unenrolled students can view the questions, but not interact with them.
* Feedback on correctness is provided after an answer is submitted.
* The correct answer is revealed after completion.

The rules for this can be written as follows::

    title: "Quiz: Lecture 13"
    description: |

        # Quiz: Lecture 13

    rules:
        tags:
        - regular
        - practice

        start:
        -
            if_has_role: [unenrolled]
            may_start_new_session: True
            may_list_existing_sessions: False

        -
            if_after: lecture 13 - 4 weeks
            if_before: lecture 13 + 1 week
            if_has_role: [student, ta, instructor]
            if_has_fewer_sessions_than: 3
            tag_session: regular
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            if_has_role: [student, ta, instructor]
            tag_session: practice
            may_start_new_session: True
            may_list_existing_sessions: True

        access:

        -
            if_has_role: [unenrolled]
            permissions: [view]
            message: |

                It does not look like you are enrolled in the class, that's why you
                cannot make changes below. Please verify that you are signed in,
                and then go back to the class web page and find the big blue "Enroll"
                button near the top.

        -
            if_after: end_of_class
            if_has_role: [student]
            permissions: []

        -
            if_has_role: [student, instructor, ta]
            if_in_progress: True
            permissions: [view, submit_answer, end_session, see_correctness]

        -
            if_has_role: [student, instructor, ta]
            if_in_progress: False
            permissions: [view, see_correctness, see_answer_after_submission]

        grade_identifier: "quiz_13"
        grade_aggregation_strategy: max_grade

        grading:

        -
            if_has_tag: practice
            description: "Practice session"
            generates_grade: false

        -
            if_completed_before: lecture 13
            description: "Graded session at full credit"
            due: lecture 13

        -
            if_completed_before: lecture 13 + 1 week
            description: "Graded session at half credit"
            credit_percent: 50
            due: lecture 13 + 1 week

        -
            credit_percent: 0

    pages:

    -   ....

Homework Set with Grace Period
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This rule set describes the following:

* Homework that is due at a time given by an event ``hw_due 2``.
* Visitors/unenrolled students can view the questions, but not interact with them.
* For-credit sessions are tagged as "full-credit" (``main``) or
  "half-credit" (``grace``) and earn credit correspondingly.
* Students are allowed to decide whether they would like to
  auto-submit their work at the deadline or keep working.
* Due dates are shown as given by ``hw_due 2`` and a week
  after that.
* At the deadlines (or soon after them), an instructor
  "expires" the sessions using a button in the grading interface,
  thereby actually "realizing" the deadline.
* Correct solutions are revealed after the main deadline passes.

The rules for this can be written as follows::

    title: "Homework 2"
    description: |

        # Homework 2

    rules:
        tags:
        - main
        - grace

        start:
        -
            if_has_role: [unenrolled]
            tag_session: null
            may_start_new_session: True
            may_list_existing_sessions: False

        -
            if_after: hw_due 2 - 3 weeks
            if_before: hw_due 2
            if_has_role: [student, ta, instructor]
            if_has_fewer_tagged_sessions_than: 1
            tag_session: main
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            if_after: hw_due 2
            if_before: hw_due 2 + 7 days
            if_has_role: [student, ta, instructor]
            if_has_fewer_tagged_sessions_than: 1
            tag_session: grace
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            may_start_new_session: False
            may_list_existing_sessions: True

        access:
        -
            if_has_tag: null
            permissions: [view]

        -
            if_after: end_of_class
            if_has_role: [student]
            permissions: []

        -
            # Unfinished full-credit session marked 'end' after due date.
            if_has_tag: main
            if_in_progress: True
            if_after: hw_due 2
            if_expiration_mode: end
            message: |
              The due date has passed. If you have marked your session to
              end at the deadline, it will receive full credit, but it
              will end automatically fairly soon. If you would like to
              continue working, please mark your session to roll over
              into 50% credit by selecting 'Keep session and apply new rules'.
            permissions: [view, submit_answer, end_session, see_correctness, change_answer, set_roll_over_expiration_mode]

        -
            # Unfinished full-credit session marked 'roll_over' before due date.
            if_has_tag: main
            if_in_progress: True
            if_expiration_mode: roll_over
            message: |
              You have marked your session to roll over to 50% credit at the due
              date. If you would like to have your current answers graded as-is
              (and recieve full credit for them), please select 'End session
              and grade'.
            permissions: [view, submit_answer, end_session, see_correctness, change_answer, set_roll_over_expiration_mode]

        -
            # Unfinished Full-credit session before due date.
            if_has_tag: main
            if_in_progress: True
            permissions: [view, submit_answer, end_session, see_correctness, change_answer, set_roll_over_expiration_mode]

        -
            # Full-credit session before due date. Don't show answer.
            if_has_tag: main
            if_before: hw_due 2
            if_in_progress: False
            permissions: [view, see_correctness]

        -
            # Full-credit session after due date? Reveal answer.
            if_has_tag: main
            if_after: hw_due 2
            if_in_progress: False
            permissions: [view, see_correctness, see_answer_before_submission, see_answer_after_submission]

        -
            # You're allowed to keep working during the grace period
            if_has_tag: grace
            if_in_progress: True
            permissions: [view, submit_answer, end_session, see_correctness, change_answer, see_answer_before_submission, see_answer_after_submission]

        -
            if_has_tag: grace
            if_in_progress: False
            permissions: [view, see_correctness, see_answer_before_submission, see_answer_after_submission]

        grade_identifier: "hw_2"
        grade_aggregation_strategy: max_grade

        grading:
        -
            if_has_tag: null
            description: "No-credit preview session"
            generates_grade: false

        -
            if_has_tag: main
            credit_percent: 100
            due: hw_due 2
            description: "Full credit"

        -
            if_has_tag: grace
            credit_percent: 50
            due: hw_due 2 + 7 days
            description: "Half credit"

        -
            credit_percent: 0

    pages:

    -   ....

