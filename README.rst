CourseFlow
==========

"I just want to ask my students some quiz questions online. How hard could it
possibly be?"

CourseFlow is a `Django <https://docs.djangoproject.com/>`_-based courseware
package that lets students participate in online activities. Each such activity
is called a "flow". It flows over a couple of pages, each of which can be, say,
a video, a quiz question, a page of text, or, within the confines of HTML,
something completely different.

CourseFlow is set apart by the following features:

* Emphasizes ease of authoring, using `YAML <https://en.wikipedia.org/wiki/YAML>`_,
  `Markdown <https://en.wikipedia.org/wiki/Markdown>`_ and Python.
  See `example content <https://github.com/inducer/courseflow-sample>`_.
* Versioning of content through deep integration with `git <https://git-scm.org>`_.
  Instructors can preview newly-authored content while students work with
  prior versions, all from the same instance of CourseFlow.

Installation
------------

CourseFlow currently works with Python 2.7. (This is because `dulwich
<https://www.samba.org/~jelmer/dulwich/>`_, a dependency, does not yet support
Python 3.)

(Optional) Make a virtualenv to install to::

    virtualenv --system-site-packages my-courseflow-env
    source my-courseflow-env/bin/activate

To install, clone the repository::

    git clone --recursive git://github.com/inducer/courseflow

Enter the courseflow directory::

    cd courseflow

Install the dependencies::

    pip install -r requirements.txt

Copy (and, optionally, edit) the example configuration::

    cp local_settings.py.example local_settings.py
    vi local_settings.py

Initialize the database::

    python manage.py migrate
    python manage.py createsuperuser --username=$(whoami)

Run the server::

    python manage.py runserver

Open a browser to http://localhost:8000, sign in (your user name will be the
same as your system user name, or whatever `whoami` returned above) and select
"Set up new course".

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
