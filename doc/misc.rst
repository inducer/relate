Installation
============

RELATE currently works with Python 2.7. (This is because `dulwich
<https://www.samba.org/~jelmer/dulwich/>`_, a dependency, does not yet support
Python 3.)

Install `bower <http://bower.io/>`_ and its dependencies, as described on its
web page.

(Optional) Make a virtualenv to install to::

    virtualenv my-relate-env
    source my-relate-env/bin/activate

To install, clone the repository::

    git clone git://github.com/inducer/relate

Enter the relate directory::

    cd relate

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

Long-term maintenance
---------------------

As course content gets updated repeatedly, more and more little files get
created in the directories containing the course directories. Given enough
time, RELATE may eventually encounter this `issue in dulwich
<https://github.com/jelmer/dulwich/issues/281>`_, the software component that
RELATE uses to access git repositories. If it does, it will fail with
``IOError: [Errno 24] Too many open files``.

To prevent this from happening, it is advisable to occasionally run ``git repack -a -d``
on RELATE's git repositories. This may be accomplished by creating a
`Cron <https://en.wikipedia.org/wiki/Cron>`_ job running
a customized version of
`this script <https://github.com/inducer/relate/blob/master/repack-repositories.sh>`_.
This is needed about once every few hundred course update cycles, so relatively
infrequently.

How to translate RELATE
-----------------------

RELATE is translatable into languages other than English. Run the
following command::

    django-admin makemessages -l de

This will generate a message file for German, where the locale name ``de``
stands for Germany. The message file located in the ``locale`` directory
of your RELATE installation. For example, the above command will generate
a message file ``django.po`` in ``/project/root/locale/de/LC_MESSAGES``.

Edit ``django.po``. For each ``msgid`` string, put it's translation in
``msgstr`` right below. ``msgctxt`` strings, along with the commented
``Translators:`` strings above some ``msgid`` strings, are used to provide
more information for better understanding of the text to be translated.
A Simplified Chinese version (demo) of translation is included for Chinese
users, with locale name ``zh_CN``.


When translations are done, run the following command in root directory::

    django-admin compilemessages -l de

Your translations are ready for use. If you translate RELATE, please submit
your translations for inclusion into the RELATE itself.

To enable the translations, open your ``local_settings.py``, uncomment the
``LANGUAGE_CODE`` string and change 'en-us' to the locale name of your
language. 

For more instructions, please refer to `Localization: how to create
language files <https://docs.djangoproject.com/en/dev/topics/i18n/translation/#localization-how-to-create-language-files>`_.


Tips
====

User-visible Changes
====================

Version 2015.1
--------------

First public release.

License
=======

RELATE is licensed to you under the MIT/X Consortium license:

Copyright (c) 2014-15 Andreas Klöckner and Contributors.

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
