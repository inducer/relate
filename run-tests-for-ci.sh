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

if [[ "$PY_EXE" = python2* ]]; then
  grep -Ev "django>|django=" requirements.txt > req.txt
  $PIP install "django<2"
  $PIP install mock
else
  cp requirements.txt req.txt
fi

$PIP install -r req.txt

cp local_settings_example.py local_settings.py

# Make sure i18n literals marked correctly
${PY_EXE} manage.py makemessages --no-location --ignore=req.txt > output.txt

if [[ -n $(grep "msgid" output.txt) ]]; then
    echo "Command 'python manage.py makemessages' failed with the following info:"
    echo ""
    grep --color -E '^|warning: ' output.txt
    exit 1;
fi

if [[ "$PY_EXE" = python3* ]]; then
    ${PY_EXE} manage.py compilemessages
fi

$PIP install codecov factory_boy

if [[ "$RL_TRAVIS_TEST" = "test_expensive" ]]; then
    coverage run manage.py test tests.test_tasks \
                                tests.test_admin \
                                tests.test_pages.test_code \
                                tests.test_pages.test_generic \
                                tests.test_pages.test_inline.InlineMultiPageUpdateTest \
                                tests.test_pages.test_upload.UploadQuestionNormalizeTest \
                                tests.test_grades.test_generic \
                                tests.test_grades.test_grades.GetGradeTableTest \
                                tests.test_grading.SingleCourseQuizPageGradeInterfaceTest \
                                tests.test_utils.LanguageOverrideTest \
                                tests.test_accounts.test_admin.AccountsAdminTest \
                                tests.test_flow.test_flow.AssemblePageGradesTest \
                                tests.test_flow.test_flow.FinishFlowSessionViewTest \
                                tests.test_content.SubDirRepoTest \
                                tests.test_auth.SignInByPasswordTest \
                                tests.test_analytics.FlowAnalyticsTest \
                                tests.test_analytics.PageAnalyticsTest \
                                tests.test_analytics.FlowListTest \
                                tests.test_analytics.IsFlowMultipleSubmitTest \
                                tests.test_analytics.IsPageMultipleSubmitTest \
                                tests.test_versioning.ParamikoSSHVendorTest \
                                tests.test_receivers.UpdateCouresOrUserSignalTest

else
    coverage run manage.py test tests
fi

coverage report -m
codecov
