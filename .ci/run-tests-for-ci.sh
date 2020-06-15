#! /bin/bash

set -e

PY_EXE=${PY_EXE:-$(poetry run which python)}

echo "-----------------------------------------------"
echo "Current directory: $(pwd)"
echo "Python executable: ${PY_EXE}"
echo "-----------------------------------------------"

echo "Copy local settings"


echo "i18n"
# Testing i18n needs a local_settings file even though the rest of the tests
#   don't use it
cp local_settings_example.py local_settings.py

# Make sure i18n literals marked correctly
poetry run python manage.py makemessages --no-location --ignore=req.txt > output.txt

if [[ -n $(grep "msgid" output.txt) ]]; then
    echo "Command 'python manage.py makemessages' failed with the following info:"
    echo ""
    grep --color -E '^|warning: ' output.txt
    exit 1;
fi

poetry run python manage.py compilemessages

echo "Starts testing"

if [[ "$RL_CI_TEST" = "expensive" ]]; then
    echo "Expensive tests"
    export RL_CI_TEST="test_expensive"
    poetry run coverage run ./manage.py test tests.test_tasks \
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

elif [[ "$RL_CI_TEST" = "postgres" ]]; then
    export PGPASSWORD=relatepgpass

    echo "Preparing database"
    echo "import psycopg2.extensions" >> local_settings_example.py
    echo "DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'HOST': 'localhost',
                'USER': 'postgres',
                'PASSWORD': '${PGPASSWORD}',
                'NAME': 'test_relate',
                'OPTIONS': {
                    'isolation_level': psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE,
                },
            },
        }" >> local_settings_example.py

    poetry run pip install psycopg2-binary
    # psql -c 'create database relate;' -U postgres 

    echo "Database tests"
    poetry run coverage run ./manage.py test tests.test_postgres
else
    echo "Base tests"
    poetry run coverage run ./manage.py test tests
fi

echo "Generate coverage report"
poetry run coverage xml
