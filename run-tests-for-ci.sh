#! /bin/bash

set -e

echo "-----------------------------------------------"
echo "Current directory: $(pwd)"
echo "Python executable: ${PY_EXE}"
echo "-----------------------------------------------"

# {{{ clean up

rm -Rf .env
rm -Rf build
find . -name '*.pyc' -delete

# }}}

git submodule update --init --recursive

# {{{ virtualenv

VENV_VERSION="virtualenv-15.1.0"
rm -Rf "$VENV_VERSION"
curl -k https://pypi.python.org/packages/d4/0c/9840c08189e030873387a73b90ada981885010dd9aea134d6de30cd24cb8/$VENV_VERSION.tar.gz

VIRTUALENV="${PY_EXE} -m venv"
${VIRTUALENV} -h > /dev/null || VIRTUALENV="$VENV_VERSION/virtualenv.py --no-setuptools -p ${PY_EXE}"

if [ -d ".env" ]; then
  echo "**> virtualenv exists"
else
  echo "**> creating virtualenv"
  ${VIRTUALENV} .env
fi

. .env/bin/activate

# }}}

# {{{ setuptools

#curl -k https://bitbucket.org/pypa/setuptools/raw/bootstrap-py24/ez_setup.py | python -
#curl -k https://ssl.tiker.net/software/ez_setup.py | python -
#curl -k https://bootstrap.pypa.io/ez_setup.py | python -

SETUPTOOLS_VERSION="setuptools-36.6.0"
curl -L -O -k https://pypi.python.org/packages/45/29/8814bf414e7cd1031e1a3c8a4169218376e284ea2553cc0822a6ea1c2d78/$SETUPTOOLS_VERSION.zip
unzip $SETUPTOOLS_VERSION.zip
$PY_EXE $SETUPTOOLS_VERSION/setup.py install

# }}}

curl -k https://bootstrap.pypa.io/get-pip.py | python -

# Not sure why pip ends up there, but in Py3.3, it sometimes does.
export PATH=`pwd`/.env/local/bin:$PATH

PIP="${PY_EXE} $(which pip)"

grep -v dnspython requirements.txt > req.txt
if [[ "$PY_EXE" = python2* ]]; then
  $PIP install dnspython
  $PIP install mock
else
  $PIP install dnspython3
fi

$PIP install -r req.txt

cp local_settings.example.py local_settings.py

$PIP install codecov
coverage run manage.py test tests/
coverage report -m
codecov
