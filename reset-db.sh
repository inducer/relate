#! /bin/bash

set -e

# This file is only used during initial development and completely blows away
# the test database, initial data, and existing migrations for the DB.

rm -f db.sqlite
python manage.py migrate
python manage.py changepassword $(whoami)
