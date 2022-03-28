#!/bin/bash

# verify we HAVE necessary env vars
if [ -z "$DBUSER" ] || [ -z "$DBPASS" ] || [ -z "$DBHOST" ]; then
    echo "Missing necessary environment variables!"
    env
    exit 1
fi

set -x

#set extra host headers
EXTRAHOSTS=
if [ ! -z "$HOSTS" ]; then
    IFS=";"
    for h in $HOSTS
    do
      if [ -z "${EXTRAHOSTS}" ]; then
        EXTRAHOSTS="\"$h\""
      else
        EXTRAHOSTS="${EXTRAHOSTS},\"${h}\""
      fi
    done
    unset IFS
    export EXTRAHOSTS
fi
ORIGINS=
if [ ! -z "$HOSTS" ]; then
    IFS=";"
    for h in $HOSTS
    do
      if [ -z "${ORIGINS}" ]; then
        ORIGINS="\"https://$h\""
      else
        ORIGINS="${ORIGINS},\"https://${h}\""
      fi
    done
    unset IFS
    export ORIGINS
fi

set -euo pipefail

envsubst </var/www/relate/local_settings_template.py >/var/www/relate/local_settings.py

cd /var/www/relate

# create initial db setup if necessary - and superuser
poetry run python manage.py migrate
poetry run python manage.py createsuperuser --username=relateadmin

# run directly instead of via uwsgi
poetry run python manage.py runserver 0.0.0.0:8000

# find name of virtual env - for use in uwsgi config
VENV=$(find /root/.cache/pypoetry/virtualenvs/ -name 'relate-courseware*')
echo "$VENV"


