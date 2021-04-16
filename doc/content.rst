Writing content for RELATE
==============================

.. _git-repo:

Git repository
--------------

In RELATE, one course corresponds to one Git repository.

Data for a course in RELATE is contained in a `git <http://git-scm.com/>`_
repository. RELATE understands the structure of a repository and makes use
of the version history present. For example, you could be previewing and
testing some newly developed course content, while the students continue to
work with a prior version until you make the new version explicitly available.

One revision ("commit") of the git repository is always viewed as the "current"
one. This is the one being shown to all visitors. In addition, each user (with
sufficient privileges) may be previewing a different version of their choosing.

.. note::

    When editing RELATE git repositories on Windows, make sure that the
    ``core.autocrlf`` option is set `appropriately
    <https://help.github.com/articles/dealing-with-line-endings/>`_
    (namely, so that line endings are represented in the 'UNIX' convention,
    as a single newline character).

RELATE maintains a git repository for each course and can fetch from one
external git repository configured in the course page and update its
internal git repository from this external git repository. A user with
sufficient privileges can access this internal git repository by using
``git pull`` and ``git push`` with the HTTPS URL given on the
"Update Course Content" page, RELATE username as the username and RELATE
authentication token as the password.

.. _yaml-files:

YAML
----

Most of the files in the :ref:`git-repo` defining course content are written in
`YAML <http://yaml.org/>`_. YAML is a structured plain text format. If you know
what XML is: The conceptual idea is a little like XML, but YAML is much easier
to read and write by humans than XML.

Here's an example:

.. code-block:: yaml

    title: "Homework 3"
    description: |

        # Homework 3

        Welcome to our third homework set, where you will learn about principal component analysis,
        applications of linear least squares, and more.

    rules:
        start:
        -
            if_before: end_week 1
            if_has_role: [student, ta, instructor]
            if_has_fewer_sessions_than: 2
            may_start_new_session: True
            may_list_existing_sessions: True

        -
            may_start_new_session: False
            may_list_existing_sessions: True

        access:
         -
             if_before: end_week 2
             permissions: [view, modify, see_correctness]
             message: "Welcome! This message is brought to you by the access rules."

         -
             permissions: [view, modify, see_correctness, see_answer_after_submission]

        grade_identifier: la_quiz
        grade_aggregation_strategy: max_grade

        grading:
        -
            if_completed_before: end_week 1
            credit_percent: 100

        -
            if_completed_before: end_week 2
            credit_percent: 50

        -
            credit_percent: 0
     ...

Macros in YAML
^^^^^^^^^^^^^^

Repetitive text in YAML (such as for example :ref:`flow-rules` that are
repeated for each instance of a given type of assignment, with very minor
modifications) can be abbreviated through the use of the
`Jinja <http://jinja.pocoo.org/docs/dev/templates/>`_ templating language.
Jinja expansion takes place everywhere in YAML code except for block
literals::

    # Jinja usable here

    correct_code: |

        # No Jinja here

:ref:`markup` does its own Jinja expansion though, so such block literals
*can* use Jinja.

.. ::

    (Let's keep this undocumented for now.)

    Jinja expansion *can* be enabled for a block literal by mentioning a
    letter "J" immediately after the character introducing the block scalar::

        # Jinja usable here

        correct_code: |J

            # Jinja also usable here

On system lock-in
-----------------

One key feature of RELATE is that the content you write for it is versatile
and easy to repurpose. To start, everything you write for RELATE is just
a readable, plain text file, so there are no retrieval or interpretation issues.

Next, the `pandoc <http://johnmacfarlane.net/pandoc/>`_ tool can be used to
export :ref:`markup` to essentially any other markup format under the sun,
including LaTeX, HTML, MediaWiki, Microsoft Word, and many more.

Further, YAML files are quite easy to read and traverse in most programming languages,
facilitating automated coversion.  `This example Python script
<https://github.com/inducer/relate/blob/main/contrib/flow-to-worksheet>`_
provided as part of RELATE takes a flow and converts it to a paper-based
worksheet. To do so, it makes use of `pypandoc
<https://pypi.python.org/pypi/pypandoc>`_ and `PyYAML <http://pyyaml.org/>`_.

Validation
----------

While YAML lets you define *arbitrary* structures, RELATE imposes a number of rules
on what your YAML documents should look like to be acceptable as course content.

These rules are automatically checked as part of setting a new revision of the
:ref:`git-repo` to be the active or previewed revision.

This helps avoid mistakes and ensures that the students always see a working
site.

RELATE validation is also available as a stand-alone script :command:`relate-validate`.
This runs independently of git and the web site on the content developer's
computer and provides validation feedback without having to commit and
upload the content to a RELATE site. This script can be installed by running::

    sudo pip install -r requirements.txt
    sudo python setup.py install

in the root directory of the RELATE distribution.

.. _markup:

RELATE markup
-------------

All bulk text in RELATE is written in Markdown, with a few extensions.
Here are a few resources on Markdown:

*   `The basics <https://help.github.com/articles/markdown-basics/>`_ as
    described by Github.com
*   `A 10-minute tutorial <http://markdowntutorial.com/>`_
*   `John Gruber's original definition <http://daringfireball.net/projects/markdown/>`_
*   `Markdown extensions used by RELATE <https://pythonhosted.org/Markdown/extensions/extra.html>`_

To allow easy experimentation with markup, RELATE has a "markup sandbox" in
the "Content" menu where the rendered form of any RELATE markup can
be previewed.

In addition to standard Markdown, the following extensions are
supported:

Custom URLs
^^^^^^^^^^^

A few custom URL schemas are provided to facilitate easy linking around
a RELATE site:

* The URL schema ``course:course-name`` links to another course on the same
  RELATE instance. A URL ``course:`` may be used to link to the current
  course.

* The URL schema ``flow:flow-name`` provides a link to the start page of a
  flow.

  In Markdown, this might look like this::

      Please take [today's quiz](flow:quiz-lecture-17).

  This resolves to a link to the flow contained in
  :file:`flows/quiz-lecture-17.yml`.

* The URL schema ``calendar:`` links to the course calendar page.

* The URL schema ``staticpage:some/where`` links to the page found in
  ``staticpages/some/where.yml`` in the repository.
  (Note the added ``staticpages``.)

* The URL schema ``repo:some/file/name.png``
  will be resolved to the file `some/file/name.png` in the
  course's :ref:`git-repo`.

  In Markdown, this might look like this::

      ![A bouncing ball](repo:images/bouncing-ball.gif)

  To avoid exposing sensitive files, a special file :file:`.attributes.yml`
  must be present in the same directory as the file which allows public
  access to the file. This file should be valid YAML and look like this::

      unenrolled:
      - "*.png"
      - "*.jpeg"

  In addition to ``unenrolled``, the file can also include the following
  sections:

  * ``unenrolled``: Allow access to these files from anywhere on the
    Internet, except for locked-down exam sessions.
  * ``in_exam``: Allow access to these files when a locked-down exam
    is ongoing.
  * ``student``: Allow access to these files for ``student``, ``ta``, and
    ``instructor`` roles
  * ``ta``: Allow access to these files for ``ta`` and ``instructor`` roles
  * ``instructor``: Allow access to these files only for the ``instructor`` role

* The URL schema ``repocur:some/file/name.png``
  generally works the same way as ``repo:``, with these differences:

  * Unlike ``repo:``, the links generated by this URL schema will *not*
    contain the current repository version. That means the link can safely
    be bookmarked by a user and will always deliver the current version
    of that file.

  * The generated links are also easier to create by hand and thus more
    useful for linking from outside of RELATE.

  * Links generated by ``repocur:`` cannot be cached as effectively as
    those generated by ``repo:``, and they take a few more database
    lookups to resolve. Using ``repocur:`` therefore consumes more
    bandwidth and computation on the RELATE server. As a result, it
    is advantageous to use ``repo:`` whenever practical.

.. note::

    A URL schema ``media:`` used to exist and will continue to be
    supported. Its use is discouraged in favor of ``repo:`` and
    ``repocur:``.

.. warning::

    For the continued support of the ``media:`` URL schema, the entire
    ``media/`` subdirectory of the git repository is unconditionally
    accessible from anywhere in the world, by anyone. Sensitive files
    should not be stored there.

LaTeX-based mathematics
^^^^^^^^^^^^^^^^^^^^^^^

Use ``$...$`` to enclose inline math
and ``$$...$$`` to enclose display math. This feature is provided
by `MathJax <http://www.mathjax.org/>`_.

If you would like to use AMSMath-style LaTeX environments, wrap them
in ``$$...$$``::

    $$
    \begin{align*}
    ...
    \end{align*}
    $$

Symbols and Icons
^^^^^^^^^^^^^^^^^

RELATE includes `FontAwesome <http://fontawesome.io/>`_,
a comprehensive symbol set by Dave Gandy.
Symbols from `that set <http://fontawesome.io/icons/>`_ can be included as follows::

      <i class="fa fa-heart"></i>

In-line HTML
^^^^^^^^^^^^

In addition to Markdown, HTML is also allowed and puts the
full power of modern web technologies at the content author's disposal.
Markdown and HTML may also be mixed. For example, the following
creates a box with a recessed appearance around the content::

    <div class="well" markdown="1">
      Exam 2 takes place **next week**. Make sure to [prepare early](flow:exam2-prep).
    </div>

The attribute ``markdown="1"`` instructs RELATE to continue looking
for Markdown formatting inside the HTML element.

Video
^^^^^

RELATE includes `VideoJS <http://www.videojs.com/>`_
which lets you easily include HTML5 video in your course content.
The following snippet shows an interactive video viewer::

    <video id="myvideo" class="video-js vjs-default-skin"
       controls preload="auto" width="800" height="600"
       poster="/video/cs357-f14/encoded/myvideo.jpeg"
       data-setup='{"playbackRates": [1, 1.3, 1.6, 2, 4]}'>
      <source src="/video/cs357-f14/encoded/myvideo.webm" type='video/webm' />
      <source src="/video/cs357-f14/encoded/myvideo.mp4" type='video/mp4' />
      <p class="vjs-no-js">To view this video please enable JavaScript, and consider upgrading to a web browser that <a href="http://videojs.com/html5-video-support/" target="_blank">supports HTML5 video</a></p>
    </video>


Ipython notebook to HTML
^^^^^^^^^^^^^^^^^^^^^^^^

RELATE provides the functionality of rendering `Ipython Notebooks
<https://ipython.org/ipython-doc/3/notebook/>`_ in course pages, by using
`nbconvert <http://nbconvert.readthedocs.io>`_.

.. function:: render_notebook_cells(ipynb_path, indices=None, clear_output=False,
                                  clear_markdown=False)

    :param ipynb_path: :class:`str`, the path of the ipython notebook in
        the repo.
    :param indices: :class:`list`, the indices of cells which are expected to
        be rendered. For example, ``[1, 2, 3, 6]`` or ``range(3, -1)``. If not
        specified, all cells will be rendered.
    :param clear_output: :class:`bool`, indicating whether existing execution
        output of code cells should be removed. Default: `False`.
    :param clear_markdown: :class:`bool`, indicating whether all text cells
        will be removed. Default: `False`.
    :rtype: :class:`str`, rendered markdown which will be consequently
     converted to HTML.

For example, the following snippet shows the HTML version of ``test.ipynb`` in repo
folder ``code``, with markdown (``text_cells``) and output (execution result of
``code_cells``) removed::

    {{ render_notebook_cells("code/test.ipynb", clear_markdown=True, clear_output=True) }}


Macros
^^^^^^

Repetitive text (such as the fairly long video inclusion snippet above)
can be abbreviated through the use of the `Jinja <http://jinja.pocoo.org/docs/dev/templates/>`_
templating language. For example, you could have a file :file:`macros.jinja` in the root
of your :ref:`git-repo` containing the following text::

    {% macro youtube(id) -%}
      <iframe width="420" height="315" src="//www.youtube.com/embed/{{id}}" frameborder="0" allowfullscreen>
      </iframe>
    {%- endmacro %}

This could then be used from wherever RELATE markup is allowed::

          Some text... More text...

          {% from "macros.jinja" import youtube %}
          {{ youtube("QH2-TGUlwu4") }}

          Some text... More text...

to embed a YouTube player. (YouTube is a registered trademark.)

.. _course_yml:

The Main Course Page File
-------------------------

One required part of each course repository is a :ref:`YAML file
<yaml-files>` that is typically named :file:`course.yml` Other names may be
specified, enabling multiple courses to be run from the same repository.
It has the same format as a course page, described next, and it contains
the information shown on the main course page.

"Static" (i.e. non-interactive) pages
-------------------------------------

A static page looks as follows and is either the main course file
or a file in the ``staticpages`` subfolder of the course repository.

.. class:: Page

    .. attribute:: content

        :ref:`markup`. If given, this contains the entirety of the page's
        content.
        May only specify exactly one of :attr:`content` or :attr:`chunks`.

    .. attribute:: chunks

        A list of :ref:`course-chunks`. Chunks allow dynamic reordering
        and hiding of course information based on time and rules.

        May only specify exactly one of :attr:`content` or :attr:`chunks`.

.. comment:
    .. attribute:: grade_summary_code

        Python code to categorize grades and compute summary grades.

        This code must be both valid Python version 2 and 3.

        It has access to a the following variables:

        * ``grades``: a dictionary that maps grade
          identifiers to objects with the following attributes:

          * ``points`` a non-negative floating-point number, or *None*
          * ``max_points`` a non-negative floating-point number
          * ``percentage`` a non-negative floating-point number, or *None*
          * ``done`` whether a grade of *None* should be counted as zero
            points

          The code may modify this variable.

        * ``grade_names``

          The code may modify this variable.

        It should create the following variables:

        * ``categories`` a dictionary from grade identifiers to category
          names.

        * ``cat_order`` a list of tuples ``(category_name, grade_id_list)``
          indicating (a) the order in which categories are displayed and
          (b) the order in which grades are shown within each category.

.. _course-chunks:

Course Page Chunks
^^^^^^^^^^^^^^^^^^

.. _events:

A 'chunk' of the course page is a piece of :ref:`markup` that can shown,
hidden, and ordered based on a few conditions.

Here's an example:

.. code-block:: yaml

    chunks:

    -
        title: "Welcome to the course"
        id: welcome
        rules:
        -   if_before: end_week 3
            weight: 100

        -   weight: 0

        content: |

            # Welcome to the course!

            Please take our introductory [quiz](flow:quiz-intro).

.. class:: CourseChunk

    .. attribute:: title

        A plain text description of the chunk to be used in a table of
        contents. A string. No markup allowed. Optional. If not supplied,
        the first ten lines of the page body are searched for a
        Markdown heading (``# My title``) and this heading is used as a title.

    .. attribute:: id

        An identifer used as page anchors and for tracking. Not
        user-visible otherwise.

    .. attribute:: rules

        A list of :class:`CoursePageChunkRules` that will be tried in
        order. The first rule whose conditions match determines whether
        the chunk will be shown and how where on the page it will be.
        Optional. If not given, the chunk is shown and has a default
        :attr:`CoursePageChunkRules.weight` of 0.

    .. attribute:: content

        The content of the chunk in :ref:`markup`.


.. class:: CoursePageChunkRules

    .. attribute:: weight

        (Required) An integer indicating how far up the page the block
        will be shown. Blocks with identical weight retain the order
        in which they are given in the course information file.

    .. attribute:: if_after

        (Optional) A :ref:`datespec <datespec>` that determines a date/time after which this rule
        applies.

    .. attribute:: if_before

        (Optional) A :ref:`datespec <datespec>` that determines a date/time before which this rule
        applies.

    .. attribute:: if_has_role

        (Optional) A list of a subset of the roles defined in the course, by
        default ``unenrolled``, ``ta``, ``student``, ``instructor``.

    .. attribute:: if_has_participation_tags_any

        (Optional) A list of participation tags. Rule applies when the
        participation has at least one tag in this list.

    .. attribute:: if_has_participation_tags_all

        (Optional) A list of participation tags. Rule applies if only the
        participation's tags include all items in this list.

    .. attribute:: if_in_facility

        (Optional) Name of a facility known to the RELATE web page. This rule allows
        (for example) showing chunks based on whether a user is physically
        located in a computer-based testing center (which RELATE can
        recognize based on IP ranges).

    .. attribute:: shown

        (Optional) A boolean (``true`` or ``false``) indicating whether the chunk
        should be shown.


Calendar and Events
-------------------

The word *event* in relate is a point in time that has a symbolic name.
Events are created and updated from the 'Content' menu.

Events serve two purposes:

* Their symbolic names can be used wherever a date and time would be
  required otherwise.  For example, instead of writing ``2014-10-13
  10:30:00``, you could write ``lecture 13``. This allows course content to
  be written in a way that is reusable--only the mapping from (e.g.)
  ``lecture 13`` to the real date needs to be provided--the course material
  istelf can remain unchanged.

* They are (optionally) shown in the class calendar.

For example, to create contiguously numbered ``lecture`` events for a
lecture occuring on a Tuesday/Thursday schedule, perform the following
sequence of steps:

* Create a recurring, weekly event for the Tuesday lectures, with a
  starting ordinal of 1. ("Create recurring events" in the "Instructor"
  menu.)

* Create a recurring, weekly event for the Thursday lectures, with a
  starting ordinal of 100, to avoid clashing with the previously assigned
  ordinals. ("Create recurring events" in the "Instructor" menu.)

* Renumber the events with the relevant symbolic name. ("Renumber events"
  in the "Instructor" menu.) This assigns new ordinals to all events with
  the specified symbolic name by increasing order in time.

.. _datespec:

Specifying dates in RELATE
^^^^^^^^^^^^^^^^^^^^^^^^^^

In various places around its :ref:`YAML documents <yaml-files>`, RELATE
allows dates to be specified. The following formats are supported:

* ``symbolic_name ordinal`` (e.g. ``lecture 13``) to refer to the start time of
  :ref:`calendar events <events>` with an ordinal.

* ``symbolic_name`` (e.g. ``final_exam``) to refer to the start time of
  :ref:`calendear events <events>` *without* an ordinal.

* ``end:symbolic_name ordinal`` (e.g. ``end:lecture 13``) to refer to the end time
  of :ref:`calendar events <events>` with an ordinal.

* ``end:symbolic_name`` (e.g. ``end:final_exam``) to refer to the end time of
  :ref:`calendar events <events>` *without* an ordinal.

* ISO-formatted dates (``2014-10-13``)

* ISO-formatted times (``2014-10-13 14:13``)

Each date may be modified by adding further modifiers:

* ``+/- N (weeks|days|hours|minutes)`` (e.g. ``hw_due 3 + 1 week``)
* ``@ 23:59`` (e.g. ``hw_due 3 @ 23:59``) to adjust the time of the event to
  a given time-of-day.

Multiple of these modifiers may occur. They are applied from left to right.

.. events_yml

The Calendar Information File: :file:`events.yml`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The calendar information file, by default named :file:`events.yml`,
augments the calendar data in the database with descriptions and
other meta-information. It has the following format:

.. code-block:: yaml

    event_kinds:
        lecture:
            title: Lecture {nr}
            color: blue

        exam:
            title: Exam {nr}
            color: red

    events:
        "lecture 1":
            title: "Alternative title for lecture 1"
            color: red
            description: |
                *Pre-lecture material:* [Linear algebra pre-quiz](flow:prequiz-linear-algebra) (not for credit)

                * What is Scientific Computing?
                * Python intro

The first section, ``event_kinds``, provides color and titling information that
applies to all events sharing a symbolic name. The string ``{nr}`` is automatically replaced
by the 'ordinal' of each event.

The secondsection, ``events``, can be used to provide a more verbose
description for each event that appears below the main calendar. Titles and
colors can also be overriden for each event specifically.

All attributes in each section (as well as the entire calendar information
file) are optional.

.. # vim: textwidth=75
