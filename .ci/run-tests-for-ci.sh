#! /bin/bash

set -e

PY_EXE=${PY_EXE:-$(poetry run which python)}

echo "-----------------------------------------------"
echo "Current directory: $(pwd)"
echo "Python executable: ${PY_EXE}"
echo "-----------------------------------------------"

echo "i18n"
# Testing i18n needs a local_settings file even though the rest of the tests
#   don't use it
cp local_settings_example.py local_settings.py

# Make sure i18n literals marked correctly
poetry run python manage.py makemessages -a --no-location --ignore=req.txt > output.txt

if [[ -n $(grep "msgid" output.txt) ]]; then
    echo "Command 'python manage.py makemessages' failed with the following info:"
    echo ""
    grep --color -E '^|warning: ' output.txt
    exit 1;
fi

poetry run python manage.py compilemessages

echo "Starts testing"
export RELATE_LOCAL_TEST_SETTINGS="local_settings_example.py"

PYTEST_COMMON_FLAGS="--cov-config=setup.cfg --cov-report=xml --cov=. --tb=native"
if [[ "$RL_CI_TEST" = "expensive" ]]; then
    echo "Expensive tests"
    poetry run pytest $PYTEST_COMMON_FLAGS --slow
elif [[ "$RL_CI_TEST" = "postgres" ]]; then
    export PGPASSWORD=relatepgpass

    echo "Preparing database"
    echo "import psycopg2.extensions" >> local_settings_example.py
    echo "DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'HOST': 'localhost',
                'USER': 'postgres',
                'PASSWORD': '${PGPASSWORD}',
                'NAME': 'test_relate',
                'OPTIONS': {
                    'isolation_level': psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE,
                },
            },
        }" >> local_settings_example.py

    poetry run pip install psycopg2
    echo "Database tests"
    poetry run pytest $PYTEST_COMMON_FLAGS
else
    echo "Base tests"
    poetry run pytest $PYTEST_COMMON_FLAGS
fi
