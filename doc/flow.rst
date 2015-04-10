Flows
=====

.. currentmodule:: course.constants

All interactive content in RELATE is part of a *flow*. Here is a complete
example:

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
          if_before: 2015-03-06 23:59:00
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
           if_before: 2015-03-06 23:59:00
           permissions: [view, modify, see_correctness]

         -
           permissions: [view, see_correctness, see_answer]

      # Record grades under the machine-readable name 'test_quiz'.
      # If there is more than one grade, use the maximum.
      grading:
        -
          grade_identifier: test_quiz
          grade_aggregation_strategy: max_grade

    groups:
     - id: intro
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

When described in YAML,
a flow has the following components:

.. class:: Flow

    .. attribute:: title

        A plain-text title of the flow

    .. attribute:: description

        A description in :ref:`markup` shown on the start page of the flow.

    .. attribute:: completion_text

        Some text in :ref:`markup` shown once a student has completed the flow.

    .. attribute:: rules

        (Optional) Some rules governing students' use and grading of the flow.
        See :ref:`flow-rules`.

    .. attribute:: groups

        A list of :class:`PageGroup`

Pages (the units making up a flow) come in groups. Each group has the
following attributes:

.. class:: PageGroup

    .. attribute:: id

        An identifier for this group of pages.

    .. attribute:: pages

        A list of :ref:`pages <flow-page>`

.. _flow-rules:

Flow rules
----------

Here's a commented example:

.. code-block:: yaml

    rules:
      start:
        # Rules that govern when a new session may be started and whether
        # existing sessions may be listed.

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

      access:
        # Rules that govern what a user may do with an existing session.
         -
           # Before the event 'end_week 2', a user may view, submit answers
           # to the flow, and see the grade they received for their answers.

           if_before: end_week 2
           permissions: [view, modify, see_correctness]

         -
           # Afterwards, they will also be allowed to see the correct answer.
           permissions: [view, modify, see_correctness, see_answer]

      grading:
        # Rules that govern how (permanent) grades are generated from the
        # results of a flow.

        -
          # If the user completes the flow before the event 'end_week 1', a
          # grade with identifier 'la_quiz' is generated. Multiple such grades
          # (if present) are aggregated by taking their maximum.

          if_completed_before: end_week 1
          grade_identifier: la_quiz
          grade_aggregation_strategy: max_grade

        -
          # Do not generate a grade otherwise
          grade_identifier: null

.. class:: FlowRules

    Found in the ``rules`` attribute of a flow.

    .. attribute:: start

        A list of :class:`FlowStartRules`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. attribute:: access

        A list of :class:`FlowAccessRules`.

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

    .. attribute:: grading

        A list of :class:`FlowGradingRules`

        Rules are tested from top to bottom. The first rule
        whose conditions apply determines the access.

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

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) restricting flow starting based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: if_has_fewer_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer than this
        number of sessions.

    .. attribute:: if_has_fewer_tagged_sessions_than

        (Optional) An integer. The rule applies if the participant has fewer than this
        number of sessions with access rule tags.

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

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

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

    .. rubric:: Rules specified

    .. attribute:: permissions

        A list of :class:`flow_permission`.

        :attr:`flow_permission.submit_answer` and :attr:`flow_permission.end_session`
        are automatically removed from a finished (i.e. not 'in-progress')
        session.

    .. attribute:: message

        (Optional) Some text in :ref:`markup` that is shown to the student in an 'alert'
        box at the top of the page if this rule applies.

.. class:: FlowGradingRules

    Rules that govern how (permanent) grades are generated from the
    results of a flow.

    Found in the ``grading`` attribute of :class:`FlowRules`.

    .. rubric:: Conditions

    .. attribute:: if_has_role

        (Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: if_has_tag

        (Optional) Rule applies if session has this tag (see :attr:`FlowStartRules.tag_session`),
        an identifier.

    .. attribute:: if_completed_before

        (Optional) A :ref:`datespec <datespec>`. Rule applies if the session was completed before
        this time.

    .. rubric:: Rules specified

    .. attribute:: grade_identifier

        (Required) The identifier of the grade to be generated once the
        participant completes the flow.  If ``null``, no grade is generated.

    .. attribute:: grade_aggregation_strategy

        (Mandatory if :attr:`grade_identifier` is not ``null``)

        One of :class:`grade_aggregation_strategy`.

    .. attribute:: credit_percent

        (Optional) A number indicating the percentage of credit assigned for this flow.
        Defaults to 100 if not present.

    .. attribute:: due

        A :ref:`datespec <datespec>` indicating the due date of the flow. This is shown to the
        participant and also used to batch-expire 'past-due' flows.

    .. attribute:: description

        (Optional) A description of this set of grading rules being applied to the flow.
        Shown to the participant on the flow start page.


.. autoclass:: grade_aggregation_strategy

.. _flow-permissions:

Permissions
-----------

RELATE currently supports the following permissions:

.. autoclass:: flow_permission

The ``modify`` permission is automatically removed from
a finished session.

.. _page-permissions:

Per-page permissions
^^^^^^^^^^^^^^^^^^^^

.. _flow-life-cycle:

Life cycle
----------

.. autoclass:: flow_session_expiration_mode

.. _flow-page:

Flow pages
----------

.. currentmodule:: course.page

The following page types are predefined:

* :class:`Page` -- a page of static text
* :class:`TextQuestion` -- a page allowing a textual answer
* :class:`SurveyTextQuestion` -- a page allowing an ungraded textual answer
* :class:`ChoiceQuestion` -- a multiple-choice question
* :class:`SurveyChoiceQuestion` -- a page allowing an ungraded multiple-choice answer
* :class:`PythonCodeQuestion` -- an autograded code question
* :class:`PythonCodeQuestionWithHumanTextFeedback`
  -- a code question with automatic *and* human grading
* :class:`FileUploadQuestion`
  -- a question allowing a file upload and human grading

.. |id-page-attr| replace::

    A short identifying name, unique within the page group. Alphanumeric
    with dashes and underscores, no spaces.

.. |title-page-attr| replace::

    The page's title, a string. No markup allowed. Optional. If not supplied,
    the first five lines of the page body are searched for a first-level
    Markdown heading (``# My title``) and this heading is used as a title.

.. |access-rules-page-attr| replace::

    Optional. See :ref:`page-permissions`.

.. |value-page-attr| replace::

    An integer or a floating point number, representing the
    point value of the question.

.. |text-widget-page-attr| replace::

    Optional.
    One of ``text_input`` (default), ``textarea``, ``editor:yaml``,
    ``editor:markdown``.

.. autoclass:: Page()
.. autoclass:: TextQuestion()
.. autoclass:: SurveyTextQuestion()
.. autoclass:: ChoiceQuestion()
.. autoclass:: SurveyChoiceQuestion()
.. autoclass:: PythonCodeQuestion()
.. autoclass:: PythonCodeQuestionWithHumanTextFeedback()
.. autoclass:: FileUploadQuestion()

Definining your own page types
------------------------------

.. autoclass:: PageContext
.. autofunction:: get_auto_feedback
.. autoclass:: AnswerFeedback
.. autoclass:: PageBase

.. currentmodule:: course.page.base
.. autoclass:: PageBaseWithTitle
.. autoclass:: PageBaseWithHumanTextFeedback
.. autoclass:: PageBaseWithCorrectAnswer
