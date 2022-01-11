Installation
============

RELATE requires Python 3.

Minimal Install for Validating Course Content
---------------------------------------------

Make a virtualenv, install poetry and relate::

    python3 -m venv my-relate-venv
    source my-relate-venv/bin/activate
    pip install poetry
    git clone https://github.com/inducer/relate.git
    cd relate
    poetry install

After this, you can delete the ``relate`` git checkout created. In order to
use the ``relate`` comand, you need to activate the virtualenv that was created::

    source my-relate-venv/bin/activate

Installation for Relate Development
-----------------------------------

Install `Node.js <https://nodejs.org>`__ and NPM.

Install `poetry <https://python-poetry.org>`__ to manage dependencies and virtual
environments::

    curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3

Note that this will put poetry in ``$HOME/.poetry/bin`` and modify your
``$HOME/.profile``. If you don't like that, see the
`poetry docs <https://python-poetry.org/docs/>`__ for alternate installation options.

To install, clone the repository::

    git clone https://github.com/inducer/relate.git

Enter the relate directory::

    cd relate

Install the dependencies. Poetry will automatically create a virtualenv
(somewhere under ``$HOME/.poetry``) for this:

    poetry install

Activate the virtual environment::

    poetry shell

Copy (and, optionally, edit) the example configuration::

    cp local_settings_example.py local_settings.py
    $EDITOR local_settings.py

Initialize the database::

    python manage.py migrate
    python manage.py createsuperuser --username=$(whoami)

Retrieve frontend (JS/CSS) dependencies and build::

    npm install
    npm run build

Run the server::

    python manage.py runserver

Open a browser to http://localhost:8000, sign in (your user name will be the
same as your system user name, or whatever ``whoami`` returned above) and select
"Set up new course".

As you play with the web interface, you may notice that some long-running tasks
just sit there: That is because RELATE relies on a task queue to process
those long-running tasks. Start a worker by running::

    celery worker -A relate

.. note::

    For Windows, you need first install `gevent` by::

        pip install gevent

    and then run::

        celery worker -A relate -P gevent

    See the `related issue <https://stackoverflow.com/a/47331438/3437454>`_ for more information.

To make this work, you also need a message broker running. This uses the
setting ``CELERY_BROKER_URL`` in ``local_settings.py`` and defaults to
``'amqp://'``.  With that setting, you need for example `RabbitMQ
<https://www.rabbitmq.com/>`_ or another implementation installed.  On
Debian-like Linux distributions (e.g. Ubuntu), the following should suffice::

    apt-get install rabbitmq-server

.. note::

    To install RabbitMQ for Windows, see `Installing on Windows
    <https://www.rabbitmq.com/install-windows.html>`_ for more information.

See the `Celery documentation
<http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-broker_url>`_
for more information on alternate brokers and settings.

Note that, due to limitations of the demo configuration (i.e. due to not having
out-of-process caches available), long-running tasks can only show
"PENDING/STARTED/SUCCESS/FAILURE" as their progress, but no more detailed
information. This will be better as soon as you provide actual caches (the "CACHES"
option :file:`local_settings.py`).


Additional setup steps for Docker
---------------------------------

To allow running code questions, install docker and give Relate access. The simplest
way to do so is (on a Debian/Ubuntu system)::

    apt install docker.io

Then add the user that runs Relate to the ``docker`` group in
:file:`/etc/group`.  For deployment, this may be the ``www-data`` user.
You should also pull the default container image::

    docker pull inducer/relate-runpy-amd64

Add to kernel command line, if needed::

    [...] cgroup_enable=memory swapaccount=1

Change docker config to disallow IP forwarding::

    --ip-forward=false

in :file:`/etc/default/docker.io`.

If you need more scalable code execution, consider Docker Swarm.

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

Setting up SAML2
----------------

- Install ``xmlsec1``.

- Flip ``RELATE_SIGN_IN_BY_SAML2_ENABLED`` to ``True``.

- Edit :file:`saml_config.py` using :file:`saml_config.py.example`
  as a guide.

Setting up Social Authentication (Google as an example)
-------------------------------------------------------

- Go to the `Google Developer Console <https://console.developers.google.com>`__.
- Create a project.
- Create an OAuth consent screen. You'll only need the ``.../auth/userinfo.email``
  and ``.../auth/userinfo.profile`` scopes.
- Under "Credentials", create an OAuth 2.0 Client ID. Enter your equivalent of
  ``https://relate.cs.illinois.edu/social-auth/complete/google-oauth2/`` as
  an authorized redirect URI. For testing, you can also add
  ``http://localhost:8000/social-auth/complete/google-oauth2/``.
  You do not need any authorized JavaScript origins.
- Add ``"social_core.backends.google.GoogleOAuth2"`` to
  ``RELATE_SOCIAL_AUTH_BACKENDS``.
- Copy the Client ID into ``SOCIAL_AUTH_GOOGLE_OAUTH2_KEY``, and the
  Client Secret from the developer console into ``SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET``.
- Restart your server. You should be good to go.

Deployment
----------

The following assumes you are using systemd on your deployment system.

Additional Setup Steps for Deploying to Production
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*   Install nginx for reverse proxying and uwsgi to run the app server. See below
    for configuration.
*   Use postgres as a database. You need to create a user and a database that relate
    will use and enter the details (database name, user name, password) into
    :file:`local_settings.py`. You will also need to::

        pip install psycopg2

*   The directory specified under ``GIT_ROOT`` must be owned by the user
    running Relate.

*   Run::

        python manage.py collectstatic

    to assemble the required collection of static files to be served, as the
    production app server will not serve them (unlike the dev server).

Configuring uwsgi
^^^^^^^^^^^^^^^^^

The following should be in :file:`/etc/uwsgi/apps-available/relate.ini`::

    [uwsgi]
    plugins = python
    # or plugins = python3
    socket = /tmp/uwsgi-relate.sock
    chdir=/home/andreas/relate
    virtualenv=/home/andreas/my-relate-env
    module=relate.wsgi:application
    need-app = 1
    reload-mercy=8
    max-requests=300
    workers=8
    autoload=false

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

    PermissionsStartOnly=true
    ExecStartPre=/bin/mkdir -p /var/run/celery
    ExecStartPre=/bin/chown -R www-data:www-data /var/run/celery/

    ExecStart=/home/andreas/my-relate-env/bin/celery -A relate multi start worker \
        --pidfile=/var/run/celery/celery.pid \
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

Enabling I18n support/Translating RELATE into other Languages
=============================================================

Creating New Translations
-------------------------

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
users, with locale name ``zh_HANS``.

Enabling Translations
---------------------

When translations are done, run the following command in root directory::

    django-admin compilemessages -l de

Your translations are ready for use. If you translate RELATE, please submit
your translations for inclusion into the RELATE itself.

To enable the translations, open your ``local_settings.py``, uncomment the
``LANGUAGE_CODE`` string and change 'en-us' to the locale name of your
language.

For more instructions, please refer to `Localization: how to create
language files <https://docs.djangoproject.com/en/dev/topics/i18n/translation/#localization-how-to-create-language-files>`_.

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
