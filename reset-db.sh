#! /bin/bash

set -e
set -x

# This file is only used during initial development and completely blows away
# the test database, initial data, and existing migrations for the DB.

rm -f db.sqlite3
python manage.py migrate
python manage.py createsuperuser --username=$(whoami) --email=inform@tiker.net
