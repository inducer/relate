Coursely
========

*"I just want to ask my students some quiz questions online. How hard could it
possibly be?"*

Coursely is a `Django <https://docs.djangoproject.com/>`_-based courseware
package that lets students participate in online activities. Each such activity
is called a "flow". It flows over a couple of pages, each of which can be, say,
a video, a quiz question, a page of text, or, within the confines of HTML,
something completely different.

Coursely is set apart by the following features:

* Emphasizes ease of authoring, using `YAML <https://en.wikipedia.org/wiki/YAML>`_,
  `Markdown <https://en.wikipedia.org/wiki/Markdown>`_ and Python.
  See `example content <https://github.com/inducer/coursely-sample>`_.
* Versioning of content through deep integration with `git <https://git-scm.org>`_.
  Instructors can preview newly-authored content while students work with
  prior versions, all from the same instance of Coursely.
* Code questions:

  * Allow students to write Python code into a text box (with syntax highlighting)
  * Sandboxed execution
  * Automatic grading
  * Plotting through integration with `matplotlib <http://matplotlib.org>`_
  * Optional second-stage grading by a human

* Class calendar and grade book included.
* Statistics of student answers.
* Allows live quizzes in the classroom.
* In-class instant messaging via XMPP.
  Works well with `xmpp-popup <https://github.com/inducer/xmpp-popup>`_.
* Built-in support for `VideoJS <http://www.videojs.com/>`_ offers
  easy-to-use support for integrating HTML5 video into course content
  without the need for third-party content hosting.

More information around the web:

* `See it in action <https://coursely.cs.illinois.edu/course/cs357-f14>`_
* `Documentation <http://documen.tician.de/coursely>`_

Installation
------------

See the `installation guide <http://documen.tician.de/coursely/misc.html#installation>`_.

License
-------

Copyright (C) 2014 Andreas Kloeckner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
