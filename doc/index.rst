Welcome to RELATE's documentation!
======================================

+-------------------------------------+-------------------------------------+
| .. image:: images/screenshot.png    | .. image:: images/screenshot-2.png  |
+-------------------------------------+-------------------------------------+

Features
--------

RELATE is a web-based courseware package.  It is set apart by the following
features:

* Focus on easy content creation

  * Simple, text-based format for reusable course content
  * Based on standard `YAML <https://en.wikipedia.org/wiki/YAML>`_,
    `Markdown <https://en.wikipedia.org/wiki/Markdown>`_

  See `example content <https://github.com/inducer/relate-sample>`_.

* Flexible rules for participation, access, and grading
* Versioning of content through deep integration with `git <https://git-scm.org>`_.
  Instructors can preview newly-authored content while students work with
  prior versions, all from the same instance of RELATE.
* Multiple courses can be hosted on the same installation
* Code questions:

  * Allow students to write code into a text box (with syntax highlighting)
  * Sandboxed execution
  * Automatic grading
  * Plotting support
  * Optional second-stage grading by a human

* Class calendar and grade book functionality.
* Statistics/analytics of student answers.
* Facilitates live quizzes in the classroom.
* In-class instant messaging via XMPP.
  Works well with `xmpp-popup <https://github.com/inducer/xmpp-popup>`_.
* Built-in support for `VideoJS <http://www.videojs.com/>`_ offers
  easy-to-use support for integrating HTML5 video into course content
  without the need for third-party content hosting.

RELATE is a based on the popular `Django <https://docs.djangoproject.com/>`_
web framework for Python.  It lets students participate in online activities,
each of which is (generically) called a "flow", which allows a sequence of
pages, each of which can be both static or interactive content, for exapmle a
video, a quiz question, a page of text, or, within the confines of HTML,
something completely different.

Links
-----

More information around the web:

* `Documentation <http://documen.tician.de/relate>`_
* `Source code <https://github.com/inducer/relate>`_

Table of Contents
-----------------

.. toctree::
    :maxdepth: 3

    content
    flow
    page
    api
    faq
    misc

* :ref:`genindex`

