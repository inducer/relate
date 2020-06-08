#! /bin/bash

set -e
set -x

PY_EXE="$1"

if test "$PY_EXE" = ""; then
  PY_EXE="python3.6"
fi
shift

echo "-----------------------------------------------"
echo "Current directory: $(pwd)"
echo "Python executable: ${PY_EXE}"
echo "-----------------------------------------------"

# {{{ clean up

rm -Rf .env
rm -Rf build
find . -name '*.pyc' -delete

rm -Rf env
git clean -fdx -e siteconf.py -e boost-numeric-bindings -e local_settings.py

if test `find "siteconf.py" -mmin +1`; then
  echo "siteconf.py older than a minute, assumed stale, deleted"
  rm -f siteconf.py
fi

# }}}

# {{{ virtualenv

${PY_EXE} -m ensurepip
${PY_EXE} -m pip install poetry

# }}}

poetry install

git clone https://github.com/inducer/relate-sample
cd relate-sample

relate validate .
relate test-code questions/autograded-python-example.yml
relate expand-yaml flows/quiz-test.yml > /dev/null

