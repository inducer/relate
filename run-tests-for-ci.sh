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

VENV_VERSION="virtualenv-13.0.3"
rm -Rf "$VENV_VERSION"
curl -k https://pypi.python.org/packages/source/v/virtualenv/$VENV_VERSION.tar.gz | tar xfz -

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

SETUPTOOLS_VERSION="setuptools-17.1.1"
curl -k https://pypi.python.org/packages/source/s/setuptools/$SETUPTOOLS_VERSION.tar.gz | tar xfz -
$PY_EXE $SETUPTOOLS_VERSION/setup.py install

# }}}

curl -k https://gitlab.tiker.net/inducer/pip/raw/7.0.3/contrib/get-pip.py | python -

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

python manage.py test test/
