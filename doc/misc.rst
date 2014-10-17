Installation
============

CourseFlow currently works with Python 2.7. (This is because `dulwich
<https://www.samba.org/~jelmer/dulwich/>`_, a dependency, does not yet support
Python 3.)

Install `bower <http://bower.io/>`_ and its dependencies, as described on its
web page.

(Optional) Make a virtualenv to install to::

    virtualenv --system-site-packages my-courseflow-env
    source my-courseflow-env/bin/activate

To install, clone the repository::

    git clone git://github.com/inducer/courseflow

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

Retrieve static (JS/CSS) dependencies::

    python manage.py bower install

Run the server::

    python manage.py runserver

Open a browser to http://localhost:8000, sign in (your user name will be the
same as your system user name, or whatever `whoami` returned above) and select
"Set up new course".

Additional setup steps for Docker
---------------------------------

(TODO)

Add to kernel command line, if needed::

    [...] cgroup_enable=memory swapaccount=1

Change docker config to disallow IP forwarding::

    --ip-forward=false

in :file:`/etc/default/docker.io`.


Tips
====

User-visible Changes
====================

Version 2014.1
--------------

First public release.

License
=======

CourseFlow is licensed to you under the MIT/X Consortium license:

Copyright (c) 2014 Andreas Klöckner and Contributors.

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
