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

    external_resources:

    -
        title: Numpy
        url: https://numpy.org/doc/

    completion_text: |

        # See you in class!

        Thanks for completing the quiz.

Overall Structure of a Flow
---------------------------

When described in YAML, a flow has the following components:

.. currentmodule:: course.content

.. autoclass:: FlowDesc

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

.. autoclass:: FlowRulesDesc

Rules for starting new sessions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: FlowSessionStartRuleDesc

Rules about accessing and interacting with a flow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: FlowSessionAccessRuleDesc

.. _flow-permissions:

Access permission bits
~~~~~~~~~~~~~~~~~~~~~~

.. currentmodule:: course.constants

.. autoclass:: flow_permission


Determining how final (overall) grades of flows are computed
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. currentmodule:: course.content

.. autoclass:: FlowSessionGradingRuleDesc

.. currentmodule:: course.constants

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

.. currentmodule:: course.content

.. autoclass:: FlowPageGroupDesc

.. _page-permissions:

Per-page permissions
^^^^^^^^^^^^^^^^^^^^

The granted access permissions for the entire flow (see
:class:`~course.content.FlowSessionAccessRuleDesc`) can be modified on a
per-page basis.  This happens in the ``access_rules`` sub-block of each page,
e.g. in :attr:`course.page.ChoiceQuestion.access_rules`:

.. class:: PageAccessRules

    .. attribute:: add_permissions

        A list of :class:`~course.constants.flow_permission` values that are
        granted *in addition* to the globally granted ones.

    .. attribute:: remove_permissions

        A list of :class:`~course.constants.flow_permission` values that are
        not granted for this page even if they are granted by the global flow
        permissions.

For example, to grant permission to revise an answer on a
:class:`course.page.PythonCodeQuestion`, one might type::

    type: PythonCodeQuestion
    id: addition
    access_rules:
        add_permissions:
            - change_answer
    value: 1

.. _tabbed-page-view:

Tabbed page view
^^^^^^^^^^^^^^^^^^^^

A flow page can be displayed in a tabbed view, where the first tab is the
flow page itself, and the subsequent tabs are additional external websites. 

An example use case is when the participant does not have access to
browser-native tab functionality. This is the case when using the
"Guardian" browser with the "ProctorU" proctoring service.

To access the tabbed page for a flow, append `/ext-resource-tabs` to the URL.
Alternatively, you can create a link to allow users to navigate to the tabbed 
page directly. For example, `[Open tabs](ext-resource-tabs)`.

You might need to set `X_FRAME_OPTIONS` in your Django settings to allow embedding
the flow page and external websites in iframes, depending on your site's configuration.
For example, you can add the following to your `local_settings.py`:

.. code-block:: python

    X_FRAME_OPTIONS = 'ALLOWALL'  # or specify a domain like 'ALLOW-FROM https://www.yourwebsite.com'


.. autoclass:: TabDesc

.. _flow-life-cycle:

Life cycle
----------

.. currentmodule:: course.constants

.. autoclass:: flow_session_expiration_mode

.. _points-from-feedback:

Automatic point computation from textual feedback
-------------------------------------------------

If you write your textual feedback in a certain way, Relate can help you compute
the grade (and update it when rubrics change):

    - Crossed all t's [pts:1/1 #cross_t]
    - Dotted all i's [pts:2/2 #dot_i]
    - Obeyed the axiom of choice [pts:1.5/1 #ax_choice]

    The hash marks (and arbitrary identifiers after) are optional. If specified,
    they will permit Relate to automatically update the grade feedback with
    a new rubric (while maintaining point percentages for each item, as
    found by the identifier).

    If at least one "denominator" is specified, Relate will automatically
    compute the total and set the grade percentage. If no denominator
    is specified anywhere, Relate will compute the sum and set the
    point count.

    ---

    If there is a line with three or more hyphens on its own, everything
    after that line is kept unchanged when updating feedback from a rubric.

    - [pts:-1.5] Negative point contributions work, too.

.. note::

    The feedback update facility is not currently implemented (but planned!).

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
            permissions: [view, submit_answer, end_session, cannot_see_flow_result, lock_down_as_exam_session]

        -
            if_has_role: [instructor]
            permissions: [view, submit_answer, end_session, cannot_see_flow_result, lock_down_as_exam_session]

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
              (and receive full credit for them), please select 'End session
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

