#! /bin/bash

source $(dirname $0)/run-tests-for-ci.sh

$PIP install coveralls

coverage run --source=. manage.py test test/
