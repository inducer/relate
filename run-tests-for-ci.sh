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

VENV_VERSION="virtualenv-15.2.0"
rm -Rf "$VENV_VERSION"
curl -k https://files.pythonhosted.org/packages/b1/72/2d70c5a1de409ceb3a27ff2ec007ecdd5cc52239e7c74990e32af57affe9/$VENV_VERSION.tar.gz | tar xfz -

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
curl -k https://bootstrap.pypa.io/ez_setup.py | python -

# }}}

curl -k https://bootstrap.pypa.io/get-pip.py | python -

# Not sure why pip ends up there, but in Py3.3, it sometimes does.
export PATH=`pwd`/.env/local/bin:$PATH

PIP="${PY_EXE} $(which pip)"

$PIP install -r requirements.txt

cp local_settings_example.py local_settings.py

if [[ "$RL_CI_TEST" = "test_postgres" ]]; then
    $PIP install psycopg2-binary
    psql -c 'create database relate;' -U postgres
    echo "import psycopg2.extensions" >> local_settings_example.py
    echo "DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'USER': 'postgres',
                'NAME': 'test_relate',
                'OPTIONS': {
                    'isolation_level': psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE,
                },
            },
        }" >> local_settings_example.py
fi

# Make sure i18n literals marked correctly
${PY_EXE} manage.py makemessages --no-location --ignore=req.txt > output.txt

if [[ -n $(grep "msgid" output.txt) ]]; then
    echo "Command 'python manage.py makemessages' failed with the following info:"
    echo ""
    grep --color -E '^|warning: ' output.txt
    exit 1;
fi

${PY_EXE} manage.py compilemessages

$PIP install codecov factory_boy pytest-django pytest-cov

PYTEST_FLAGS="-rxsw --durations=10 --tb=native  --junitxml=pytest.xml --cov=relate --cov=course --cov=accounts"

cd tests
if [[ "$RL_CI_TEST" = "test_expensive" ]]; then
    ${PY_EXE} -m pytest $PYTEST_FLAGS \
                                test_tasks \
                                test_admin \
                                test_pages.test_code \
                                test_pages.test_generic \
                                test_pages.test_inline.InlineMultiPageUpdateTest \
                                test_pages.test_upload.UploadQuestionNormalizeTest \
                                test_grades.test_generic \
                                test_grades.test_grades.GetGradeTableTest \
                                test_grading.SingleCourseQuizPageGradeInterfaceTest \
                                test_utils.LanguageOverrideTest \
                                test_accounts.test_admin.AccountsAdminTest \
                                test_flow.test_flow.AssemblePageGradesTest \
                                test_flow.test_flow.FinishFlowSessionViewTest \
                                test_content.SubDirRepoTest \
                                test_auth.SignInByPasswordTest \
                                test_analytics.FlowAnalyticsTest \
                                test_analytics.PageAnalyticsTest \
                                test_analytics.FlowListTest \
                                test_analytics.IsFlowMultipleSubmitTest \
                                test_analytics.IsPageMultipleSubmitTest \
                                test_versioning.ParamikoSSHVendorTest \
                                test_receivers.UpdateCouresOrUserSignalTest

elif [[ "$RL_CI_TEST" = "test_postgres" ]]; then
    ${PY_EXE} -m pytest $PYTEST_FLAGS test_postgres

else
    ${PY_EXE} -m pytest $PYTEST_FLAGS
fi

coverage report -m
codecov
