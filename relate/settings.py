"""
Django settings for relate project.

For more information on this file, see
https://docs.djangoproject.com/en/dev/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/dev/ref/settings/
"""

# Do not change this file. All these settings can be overridden in
# local_settings.py.

from django.conf.global_settings import (
        TEMPLATE_CONTEXT_PROCESSORS, STATICFILES_FINDERS)

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os
from os.path import join
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

local_settings = {}
try:
    with open(join(BASE_DIR, "local_settings.py")) as inf:
        local_settings_contents = inf.read()
except IOError:
    pass
else:
    exec(compile(local_settings_contents, "local_settings.py", "exec"),
            local_settings)

# Application definition

INSTALLED_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "course",
    "crispy_forms",
    "jsonfield",
    "bootstrap3_datetime",
    "djangobower",
)

MIDDLEWARE_CLASSES = (
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.SessionAuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "course.auth.ImpersonateMiddleware",
    "course.exam.ExamLockdownMiddleware",
)


AUTHENTICATION_BACKENDS = (
    "course.auth.TokenBackend",
    "course.exam.ExamTicketBackend",
    "django.contrib.auth.backends.ModelBackend",
    )


RELATE_EXTRA_CONTEXT_PROCESSORS = (
            "relate.utils.settings_context_processor",
            "course.auth.impersonation_context_processor",
            "course.views.fake_time_context_processor",
            "course.exam.exam_lockdown_context_processor",
            )
TEMPLATE_CONTEXT_PROCESSORS = (
        TEMPLATE_CONTEXT_PROCESSORS
        + RELATE_EXTRA_CONTEXT_PROCESSORS
        )


# {{{ bower packages

BOWER_COMPONENTS_ROOT = os.path.join(BASE_DIR, "components")

STATICFILES_FINDERS = STATICFILES_FINDERS + (
    "djangobower.finders.BowerFinder",
    )

BOWER_INSTALLED_APPS = (
    "bootstrap#3.3.4",
    "fontawesome",
    "videojs",
    "MathJax",
    "codemirror#5.2.0",
    "fullcalendar#2.3.1",
    "jqueryui",
    "datatables",
    "datatables-fixedcolumns",
    "jstree",
    )

CODEMIRROR_PATH = "codemirror"

# }}}

ROOT_URLCONF = 'relate.urls'

WSGI_APPLICATION = 'relate.wsgi.application'

CRISPY_TEMPLATE_PACK = "bootstrap3"

TEMPLATE_DIRS = (
        join(BASE_DIR, "relate", "templates"),
        )


# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

# default, likely overriden by local_settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Internationalization
# https://docs.djangoproject.com/en/dev/topics/i18n/

LANGUAGE_CODE = 'en-us'

USE_I18N = True

USE_L10N = True

USE_TZ = True

LOGIN_REDIRECT_URL = "/"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/

STATICFILES_DIRS = (
        join(BASE_DIR, "relate", "static"),
        )

STATIC_URL = '/static/'

STATIC_ROOT = join(BASE_DIR, "static")

SESSION_COOKIE_NAME = 'relate_sessionid'
SESSION_COOKIE_AGE = 12096000  # 20 weeks

RELATE_FACILITIES = {}

for name, val in local_settings.items():
    if not name.startswith("_"):
        globals()[name] = val

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": (
            join(BASE_DIR, "relate", "templates"),
            ),
        "OPTIONS": {
            "context_processors": (
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                ) + RELATE_EXTRA_CONTEXT_PROCESSORS,
            }
    },
]

LOCALE_PATHS = (
    BASE_DIR + '/locale',
)
