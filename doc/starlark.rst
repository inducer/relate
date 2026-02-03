.. _starlark:

Controlling behavior with code
==============================

Relate supports the use of `Starlark <https://starlark-lang.org/>`__ to customize
various behaviors of the system, including as an alternative approach for
specifying flow start/access/grading rules.

General notes on the language
-----------------------------

While Starlark is quite similar to Python, although a number of key differences are
worth noting:

-   No support for classes.
-   No support for exceptions, any error aborts execution.
-   No support for control flow at the top level.
-   No Python standard library, only a limited number of
    `built-in symbols <https://starlark-lang.org/spec.html#built-in-constants-and-functions>`__.
-   Modules are immutable once loaded.
-   The closest analog of Python's ``import`` statement is the ``load()`` statement.

    For example, the following ``import`` statement::

        from mymod import myfunc, other_func as other

    would be written as::

        load("mymod.star", "myfunc" other="other_func")

    ``load()`` statements may only occur at the topmost level,
    i.e. not inside of functions.

    In Relate, any file in a course's git repository can be imported via  a ``load()``
    statement, facilitating code reuse, except for those starting with
    ``relate/``, see :ref:`starlark-lib`.


Relate's implementation of Starlark includes the following extensions
of the Starlark standard:

-   f-strings, with standard Python syntax.
-   `record() <https://docs.rs/starlark/latest/starlark/values/record/>`__
    for a rough analog of Python's dataclasses.
-   `enum() <https://docs.rs/starlark/latest/starlark/values/enumeration/index.html>`__
-   ``partial()``, a workalike of :func:`~functools.partial`.
-   Type annotation, along with various symbols from :mod:`typing`, which
    are always availble, e.g. :obj:`typing.Any`.

.. _starlark-lib:

Relate's Starlark library
-------------------------

Certain functionality of the Relate system is available for use by Starlark code.
Module names starting with ``relate/`` refer to built-in functionality.

Core functionality (``relate/core.star``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.. class:: Timestamp

    An alias of :class:`float`, a UNIX timestamp.

.. function:: error(message: str) -> Never

    Abort execution with the given message.

Course-related functionality (``relate/course.star``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

(Disregard the module qualifiers given here, they are an implementation detail and
not relevant to Starlark.)

.. class:: FlowSessionExpirationMode

    An ``enum``. See :class:`course.constants.FlowSessionExpirationMode`.

.. class:: ParticipationStatus

    An ``enum``. One of "requested", "active", "dropped", "denied".

.. class:: FlowPermission
    :no-index:

    An ``enum``. See :class:`course.constants.FlowPermission`.

.. autoclass:: course.starlark.data.Participation

.. autoclass:: course.starlark.data.FlowPageId
..
.. autoclass:: course.starlark.data.FlowPageAttempt
..
.. autoclass:: course.starlark.data.FlowSession

.. function:: parse_date_spec(course: Course | None, datespec: str) -> Timestamp | None

    Parses a :ref:`datespec <datespec>` in the context of the given *course*.
    If no course is given or the *datespec* cannot be interpreted,
    *None* is returned.

    If provided, *course* must be an opaque course handle such as that
    given in :attr:`course.starlark.data.FlowSessionStartRuleArgs.course`

.. _starlark-rules:

Functionality for flow rules (``relate/rules.star``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

(Disregard the module qualifiers given here, they are an implementation detail and
not relevant to Starlark.)

.. autoclass:: course.starlark.data.FlowSessionStartRuleArgs

.. autoclass:: course.content.FlowSessionStartMode

.. autoclass:: course.starlark.data.FlowSessionAccessRuleArgs

.. autoclass:: course.utils.FlowSessionAccessMode

.. autoclass:: course.starlark.data.FlowPageAccessRuleArgs

.. autoclass:: course.utils.FlowPageAccessMode

.. function:: has_prairietest_access(course: Course | None, user_uid: str | None, user_uin: str | None, exam_uuid: str, now: float, ip_address: str, ) -> bool

    If provided, *course* must be an opaque course handle such as that
    given in :attr:`course.starlark.data.FlowSessionStartRuleArgs.course`
