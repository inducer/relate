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

As you play with the web interface, you may notice that some long-running tasks
just sit there: That is because RELATE relies on a task queue to process
those long-running tasks. Start a worker by running::

    celery worker -A relate

Note that, due to limitations of the demo configuration (i.e. due to not having
out-of-process caches available), long-running tasks can only show
"PENDING/STARTED/SUCCESS/FAILURE" as their progress, but no more detailed
information. This will be better as soon as you provide actual caches (the "CACHES"
option :file:`local_settings.py`).

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

Deployment
----------

The following assumes you are using systemd on your deployment system.

Configuring uwsgi
^^^^^^^^^^^^^^^^^

The following should be in :file:`/etc/uwsgi/apps-available/relate.ini`::

    [uwsgi]
    plugins = python
    socket = /tmp/uwsgi-relate.sock
    chdir=/home/andreas/relate
    virtualenv=/home/andreas/my-relate-env
    module=relate.wsgi:application
    need-app = 1
    reload-mercy=8
    max-requests=300
    workers=8

Then run::

    # cd /etc/uwsgi/apps-enabled
    # ln -s ../apps-available/relate.ini
    # service uwsgi restart

Configuring nginx
^^^^^^^^^^^^^^^^^

Adapt the following snippet to serve as part of your `nginx
<http://nginx.org>`_ configuration::

    server {
      listen *:80;
      listen [::]:80;
      server_name relate.cs.illinois.edu;

      rewrite ^ https://$server_name$request_uri? permanent;  # enforce https

      add_header X-Frame-Options SAMEORIGIN;
    }

    server {
      listen *:443 ssl;
      listen [::]:443 ssl;

      ssl_certificate /etc/certs/2015-01/relate-combined.crt;
      ssl_certificate_key /etc/certs/2015-01/relate.key;

      client_max_body_size 100M;

      location / {
        include uwsgi_params;
        uwsgi_read_timeout 300;
        uwsgi_pass unix:/tmp/uwsgi-relate.sock;
      }
      location /static {
        alias /home/andreas/relate/static;
      }
      location /media {
        alias /home/andreas/relate/media;
      }

      add_header X-Frame-Options SAMEORIGIN;
    }


Starting the message queue workers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use a variant of this as :file:`/etc/systemd/system/relate-celery.service`::

    [Unit]
    Description=Celery workers for RELATE
    After=network.target

    [Service]
    Type=forking
    User=www-data
    Group=www-data

    WorkingDirectory=/home/andreas/relate

    ExecStart=/home/andreas/my-relate-env/bin/celery multi start worker \
        -A relate --pidfile=/var/run/celery/celery.pid \
        --logfile=/var/log/celery/celery.log --loglevel="INFO"
    ExecStop=/home/andreas/my-relate-env/bin/celery multi stopwait worker \
        --pidfile=/var/run/celery/celery.pid

    [Install]
    WantedBy=multi-user.target

Create the directories :file:`/var/run/celery` and :file:`/var/log/celery` and
give ownership to ``www-data``::

    # mkdir /var/{run,log}/celery
    # chown www-data.www-data /var/{run,log}/celery

Then run::

    # systemctl daemon-reload
    # systemctl start relate-celery.service
    # systemctl status relate-celery.service
    # systemctl enable relate-celery.service

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
