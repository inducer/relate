from __future__ import absolute_import

"""
Django settings for RELATE.
"""

# Do not change this file. All these settings can be overridden in
# local_settings.py.

from django.conf.global_settings import STATICFILES_FINDERS

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os
from os.path import join
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

_local_settings_file = join(BASE_DIR, "local_settings.py")
local_settings = {
        "__file__": _local_settings_file,
        }
try:
    with open(_local_settings_file) as inf:
        local_settings_contents = inf.read()
except IOError:
    pass
else:
    exec(compile(local_settings_contents, "local_settings.py", "exec"),
            local_settings)

# {{{ django: apps

INSTALLED_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crispy_forms",
    "jsonfield",
    "bootstrap3_datetime",
    "djangobower",
    "django_select2",

    # message queue
    "djcelery",
    "kombu.transport.django",

    "accounts",
    "course",
)

if local_settings["RELATE_SIGN_IN_BY_SAML2_ENABLED"]:
    INSTALLED_APPS = INSTALLED_APPS + ("djangosaml2",)

# }}}

# {{{ django: middleware

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
    "course.utils.FacilityFindingMiddleware",
    "course.exam.ExamFacilityMiddleware",
    "course.exam.ExamLockdownMiddleware",
    "relate.utils.MaintenanceMiddleware",
)

# }}}

# {{{ django: auth

AUTHENTICATION_BACKENDS = (
    "course.auth.TokenBackend",
    "course.exam.ExamTicketBackend",
    "django.contrib.auth.backends.ModelBackend",
    )

if local_settings["RELATE_SIGN_IN_BY_SAML2_ENABLED"]:
    AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + (
            'course.auth.Saml2Backend',
            )

AUTH_USER_MODEL = 'accounts.User'

# }}}

# {{{ bower packages

BOWER_COMPONENTS_ROOT = os.path.join(BASE_DIR, "components")

STATICFILES_FINDERS = tuple(STATICFILES_FINDERS) + (
    "djangobower.finders.BowerFinder",
    )

BOWER_INSTALLED_APPS = (
    "bootstrap#3.3.4",
    "fontawesome#4.4.0",
    "videojs#5.6.0",
    "MathJax",
    "codemirror#5.2.0",
    "fullcalendar#2.3.1",
    "jqueryui",
    "datatables.net",
    "datatables-i18n",
    "datatables.net-bs",
    "datatables.net-fixedcolumns",
    "datatables.net-fixedcolumns-bs",
    "jstree#3.2.1",
    "select2#4.0.1",
    "select2-bootstrap-css",
    )

CODEMIRROR_PATH = "codemirror"

# }}}

ROOT_URLCONF = 'relate.urls'

WSGI_APPLICATION = 'relate.wsgi.application'

# {{{ templates

# {{{ context processors

RELATE_EXTRA_CONTEXT_PROCESSORS = (
            "relate.utils.settings_context_processor",
            "course.auth.impersonation_context_processor",
            "course.views.fake_time_context_processor",
            "course.views.pretend_facilities_context_processor",
            "course.exam.exam_lockdown_context_processor",
            )

# }}}

CRISPY_TEMPLATE_PACK = "bootstrap3"

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
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                ) + RELATE_EXTRA_CONTEXT_PROCESSORS,
            }
    },
]

# }}}

# {{{ database

# default, likely overriden by local_settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# }}}

# {{{ internationalization

LANGUAGE_CODE = 'en-us'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# }}}

LOGIN_REDIRECT_URL = "/"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/

# {{{ static

STATICFILES_DIRS = (
        join(BASE_DIR, "relate", "static"),
        )

STATIC_URL = '/static/'

STATIC_ROOT = join(BASE_DIR, "static")

# local select2 'static' resources instead of from CDN
# https://goo.gl/dY6xf7
SELECT2_JS = 'select2/dist/js/select2.min.js'
SELECT2_CSS = 'select2/dist/css/select2.css'

# }}}

SESSION_COOKIE_NAME = 'relate_sessionid'
SESSION_COOKIE_AGE = 12096000  # 20 weeks

# {{{ app defaults

RELATE_FACILITIES = {}

RELATE_TICKET_MINUTES_VALID_AFTER_USE = 0

RELATE_CACHE_MAX_BYTES = 32768

RELATE_ADMIN_EMAIL_LOCALE = "en_US"

RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION = True

# }}}

for name, val in local_settings.items():
    if not name.startswith("_"):
        globals()[name] = val

# {{{ celery config

BROKER_URL = 'django://'

CELERY_ACCEPT_CONTENT = ['pickle']
CELERY_TASK_SERIALIZER = 'pickle'
CELERY_RESULT_SERIALIZER = 'pickle'
CELERY_TRACK_STARTED = True

if "CELERY_RESULT_BACKEND" not in globals():
    if ("CACHES" in globals()
            and "LocMem" not in CACHES["default"]["BACKEND"]  # noqa
            and "Dummy" not in CACHES["default"]["BACKEND"]  # noqa
            ):
        # If possible, we would like to use an external cache as a
        # result backend--because then the progress bars work, because
        # the writes realizing them arent't stuck inside of an ongoing
        # transaction. But if we're using the in-memory cache, using
        # cache as a results backend doesn't make much sense.

        CELERY_RESULT_BACKEND = 'djcelery.backends.cache:CacheBackend'

    else:
        CELERY_RESULT_BACKEND = 'djcelery.backends.database:DatabaseBackend'

# }}}

LOCALE_PATHS = (
    BASE_DIR + '/locale',
)

# {{{ saml2

# This makes SAML2 logins compatible with (and usable at the same time as)
# email-based logins.
SAML_DJANGO_USER_MAIN_ATTRIBUTE = 'username'

SAML_CREATE_UNKNOWN_USER = True

# }}}

# This makes sure the RELATE_BASE_URL is configured.
assert local_settings["RELATE_BASE_URL"]

# This makes sure RELATE_EMAIL_APPELATION_PRIORITY_LIST is a list
if "RELATE_EMAIL_APPELATION_PRIORITY_LIST" in local_settings:
    assert isinstance(
        local_settings["RELATE_EMAIL_APPELATION_PRIORITY_LIST"], list)

# vim: foldmethod=marker
