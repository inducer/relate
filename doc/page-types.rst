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
    with underscores, no spaces.

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
    which does not require answer for full completion of the flow.  If
    ``true``, the attribute *value* should not present. Defaults to ``false``
    if not present.  Note that ``is_optional_page: true`` differs from ``value:
    0`` in that finishing flows with unanswered page(s) with the latter will be
    warned of "unanswered question(s)", while with the former won't. When using
    not-for-grading page(s) to collect answers from students, it's to better
    use ``value: 0``.

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

Fill-in-the-Blank (long-form, with formatting) (Human-graded)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. autoclass:: HumanGradedRichTextQuestion()

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
