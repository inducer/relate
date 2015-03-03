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

.. _yaml-files:

YAML
----

Most of the files in the :ref:`git-repo` defining course content are written in
`YAML <http://yaml.org/>`_. YAML is a structured plain text format. If you know
what XML is: The conceptual idea is a little like XML, but YAML is much easier
to read and write by humans than XML.

Here's an example::

    title: "Homework 3"
    description: |

        # Homework 3

        Welcome to our third homework set, where you will learn about principal component analysis,
        applications of linear least squares, and more.

    access_rules:
     - id: main
       start: lecture 12
       end: hw_due 3
       allowed_session_count: 1
       sticky: True
       permissions: [view, start_credit, view_past, see_correctness, change_answer, set_roll_over_expiration_mode]

     - id: grace
       start: hw_due 3
       end: hw_due 3 + 1 week
       allowed_session_count: 1
       credit_percent: 50
       sticky: True
       permissions: [view, start_credit, view_past, see_correctness, change_answer]

     - id: review
       start: hw_due 3 + 1 week
       permissions: [view, view_past, see_correctness, see_answer]

     - id: fallback
       permissions: []

     ...

TODO: Macro expansion in YAML

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
<https://github.com/inducer/relate/blob/master/contrib/flow-to-worksheet>`_
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
-----------------

All bulk text in RELATE is written in `Markdown
<http://daringfireball.net/projects/markdown/>`_, with a few extensions. The
linked page provides a (mostly) complete definition of the language.  A
10-minute `tutorial <http://markdowntutorial.com/>`_ is available to provide a
quick, approachable overview of Markdown.

To allow easy experimentation with markup, RELATE has a "markup sandbox" in
the "Teaching tools" menu where the rendered form of any RELATE markup can
be previewed.

In addition to standard Markdown, the following extensions are
supported:

Custom URLs
^^^^^^^^^^^

A few custom URL schemas are provided to facilitate easy linking around
a RELATE site:

* The URL schema ``flow:flow-name`` provides a link to the start page of a
  flow.

  In Markdown, this might look like this::

      Please take [today's quiz](flow:quiz-lecture-17).

  This resolves to a link to the flow contained in
  :file:`flows/quiz-lecture-17.yml`.

* The URL schema ``media:some/file/name.png``
  will be resolved to the file `media/some/file/name.png` in the
  course's :ref:`git-repo`.

  In Markdown, this might look like this::

      ![A bouncing ball](media:images/bouncing-ball.gif)

* The URL schema ``calendar:`` links to the course calendar page.

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
       data-setup='{"example_option":true}'>
      <source src="/video/cs357-f14/encoded/myvideo.webm" type='video/webm' />
      <source src="/video/cs357-f14/encoded/myvideo.mp4" type='video/mp4' />
      <p class="vjs-no-js">To view this video please enable JavaScript, and consider upgrading to a web browser that <a href="http://videojs.com/html5-video-support/" target="_blank">supports HTML5 video</a></p>
    </video>

Macros
^^^^^^

Repetitive text (such as the fairly long video inclusion snippet above)
can be abbreviated through the use of the `Jinja <http://jinja.pocoo.org/docs/dev/templates/>`_
templating language. To enable this support, make sure to use the line::

    [JINJA]

as the first line of your bulk text. From that point, you may use all features
of Jinja. For example, you could have a file :file:`macros.jinja` in the root
of your :ref:`git-repo` containing the following text::

    {% macro youtube(id) -%}
      <iframe width="420" height="315" src="//www.youtube.com/embed/{{id}}" frameborder="0" allowfullscreen>
      </iframe>
    {%- endmacro %}

This could then be used from wherever RELATE markup is allowed::

          [JINJA]

          Some text... More text...

          {% from "macros.jinja" import youtube %}

          {{ youtube("QH2-TGUlwu4") }}

          Some text... More text...

to embed a YouTube player. (YouTube is a registered trademark.)


.. _course_yml:

The Course Information File
---------------------------

The highest-level information about a course is contained in a :ref:`YAML
file <yaml-files>`_ that is typically named :file:`course.yml`. Other
names may be specified, enabling multiple courses to be run from the same
repository.

The content of this file allows the following fields:

.. class:: Course

    .. attribute:: name
    .. attribute:: number
    .. attribute:: run
    .. attribute:: chunks

        A list of :ref:`course-chunks`.

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

Here's an example::

    chunks:

      - title: "Welcome to the course"
        id: welcome
        rules:
          - if_before: end_week 3
            weight: 100

          - weight: 0

        content: |

          # Welcome to the course!

          Please take our introductory [quiz](flow:quiz-intro).

.. class:: CourseChunk

    .. attribute:: title

        A plain text description of the chunk to be used in a table of
        contents

    .. attribute:: id

        An identifer used as page anchors and for tracking. Not
        user-visible otherwise.

    .. attribute:: rules

        A list of :class:`CoursePageChunkRules` that will be tried in
        order. The first rule whose conditions match determines whether
        the chunk will be shown and how where on the page it will be.

    .. attribute:: content

        The content of the chunk in :ref:`markup`.


.. class:: CoursePageChunkRules

    .. attribute:: weight

        (required) An integer indicating how far up the page the block
        will be shown. Blocks with identical weight retain the order
        in which they are given in the course information file.

    .. attribute:: if_after

        A :ref:`datespec <datespec>` that determines a date/time after which this rule
        applies.

    .. attribute:: if_before

        A :ref:`datespec <datespec>` that determines a date/time before which this rule
        applies.

    .. attribute:: if_has_role

        A list of a subset of ``[unenrolled, ta, student, instructor]``.

    .. attribute:: shown

        A boolean (``true`` or ``false``) indicating whether the chunk
        should be shown.


Calendar and Events
-------------------

To allow course content to be reused easily from year to year, RELATE can
assign symbolic names to particular dates in your course. For example, instead
of writing ``2014-10-13``, you could write ``lecture 13`` or ``hw_due 5``.

To achieve this, each course in RELATE can store a list of events in its
database. This data serves two purposes:

* It provides data for the course calendar, available from the "Student" menu.

* It maps symbolic event names to concrete points in time, where each such
  event name consists of a symbolic name (alphanumeric+underscores) plus an
  optional number. For example, in ``lecture 13``, ``lecture`` is the symbolic
  name, and ``13`` is the ordinal.

Since this data may vary from one run of the course to the next, it is stored
along with other by-run-varying data such as grades data and not in the
:ref:`git-repo`.) A user interface to create and manipulate events is provided
in the "Instructor" menu. The same menu also contains a menu item to audit
the course content for references to symbolic event names that are not
defined.

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In various places around its :ref:`YAML documents <yaml-files>`, RELATE
allows dates to be specified. The following formats are supported:

* ``symbolic_name ordinal`` (e.g. ``lecture 13``) to refer to :ref:`calendear
  events <events>` with an ordinal.

* ``symbolic_name`` (e.g. ``final_exam``) to refer to :ref:`calendear events <events>`
  *without* an ordinal.

* ISO-formatted dates (``2014-10-13``)

* ISO-formatted times (``2014-10-13 14:13``)

Each date may be modified by adding further modifiers:

* ``+/- N (weeks|days|hours|minutes)`` (e.g. ``hw_due 3 + 1 week``)
* ``@ 23:59`` (e.g. ``hw_due 3 @ 23:59``) to adjust the time of the event to
  a given time-of-day.

Multiple of these modifiers may occur. They are applied from left to right.

.. events_yml

The Calendear Information File: :file:`events.yml`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The calendar information file, by default named :file:`events.yml`,
augments the calendar data in the database with descriptions and
other meta-information. It has the following format::

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
applies to all events sharing a symbolic name. The second, `events`, can be used
to provide a more verbose description for each event that appears below the main
calendar. Titles and colors can also be overriden for each event specifically.

All attributes in each section are optional.

.. # vim: textwidth=75
