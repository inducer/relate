Flows
=====

All interactive content in CourseFlow is part of a *flow*.

Permissions
-----------

CourseFlow currently supports the following permissions:

* 

Versioning
----------

Explain implications of sticky_versioning

Life cycle
----------

Page types
----------


Predefined page types
---------------------

.. currentmodule:: course.page

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
.. autoclass:: PageBaseWithTitle
.. autoclass:: PageBaseWithHumanTextFeedback
.. autoclass:: PageBaseWithCorrectAnswer
