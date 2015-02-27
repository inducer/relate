#! /bin/bash

set -e

rm -Rf pyz-build
mkdir pyz-build

function pywhichmod()
{
  python -c "import $1; import os.path; print($1.__file__.replace('pyc', 'py'))"
}

function pywhichpkg()
{
  python -c "import $1; import os.path; print(os.path.dirname($1.__file__))"
}

pyzzer.pyz course relate -r \
  $(pywhichmod six) \
  $(pywhichpkg markdown) \
  $(pywhichpkg django) \
  $(pywhichpkg yaml) \
  -s '#! /usr/bin/env python2.7' \
  -o relate-validate.pyz \
  -x migrations \
  -x templates \
  -x 'static/' \
  -x '\..*\.sw[op]' \
  -x 'django/db' \
  -x 'django/contrib' \
  -x 'django/core/management' \
  -x 'django/conf/locale' \
  -x 'django/test' \
  -x 'django/template' \
  -x 'django/middleware' \
  -x 'django/views' \
  -x 'django/http' \
  -x 'django/core/serial' \
  -x 'django/core/mail' \
  -x '_doctest' \
  -x '.*~' \
  -m course.validation:validate_course_on_filesystem_script_entrypoint
