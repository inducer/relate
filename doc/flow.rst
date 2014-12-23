Flows
=====

All interactive content in CourseFlow is part of a *flow*.


.. _flow-access-rules:

Access rules
------------

.. _flow-permissions:

Permissions
-----------

CourseFlow currently supports the following permissions:

.. currentmodule:: course.constants

.. autoclass:: flow_permission

.. _page-permissions:

Per-page permissions
^^^^^^^^^^^^^^^^^^^^

Versioning
----------

.. _flow-life-cycle:

Life cycle
----------

Page types
----------


Predefined page types
---------------------

.. currentmodule:: course.page

The following page types are predefined:

* :class:`Page` -- a page of static text
* :class:`TextQuestion` -- a page allowing a textual answer
* :class:`ChoiceQuestion` -- a multiple-choice question
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

.. autoclass:: Page()
.. autoclass:: TextQuestion()
.. autoclass:: ChoiceQuestion()
.. autoclass:: PythonCodeQuestion()
.. autoclass:: PythonCodeQuestionWithHumanTextFeedback()
.. autoclass:: FileUploadQuestion()

Definining your own page types
------------------------------

.. autoclass:: PageContext
.. autoclass:: NoNormalizedAnswerAvailable
.. autofunction:: get_auto_feedback
.. autoclass:: AnswerFeedback
.. autoclass:: PageBase

.. currentmodule:: course.page.base
.. autoclass:: PageBaseWithTitle
.. autoclass:: PageBaseWithHumanTextFeedback
.. autoclass:: PageBaseWithCorrectAnswer
