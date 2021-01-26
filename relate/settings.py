from __future__ import absolute_import

"""
Django settings for RELATE.
"""

from typing import Callable, Any, Union, Dict  # noqa

# Do not change this file. All these settings can be overridden in
# local_settings.py.

from django.conf.global_settings import STATICFILES_FINDERS
from django.utils.translation import gettext_noop

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import sys
import os
from os.path import join
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER = True

_local_settings_file = join(BASE_DIR, "local_settings.py")

if os.environ.get("RELATE_LOCAL_TEST_SETTINGS", None):
    # This is to make sure local_settings.py is not used for unit tests.
    assert _local_settings_file != os.environ["RELATE_LOCAL_TEST_SETTINGS"]
    _local_settings_file = os.environ["RELATE_LOCAL_TEST_SETTINGS"]

if not os.path.isfile(_local_settings_file):
    raise RuntimeError(
        "Management command '%(cmd_name)s' failed to run "
        "because '%(local_settings_file)s' is missing."
        % {"cmd_name": sys.argv[1],
           "local_settings_file": _local_settings_file})

local_settings_module_name, ext = (
    os.path.splitext(os.path.split(_local_settings_file)[-1]))
assert ext == ".py"
exec("import %s as local_settings_module" % local_settings_module_name)

local_settings = local_settings_module.__dict__  # type: ignore  # noqa

# {{{ django: apps

INSTALLED_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "social_django",
    "crispy_forms",
    "jsonfield",
    "django_select2",

    # message queue
    "django_celery_results",

    "accounts",
    "course",
)

if local_settings.get("RELATE_SIGN_IN_BY_SAML2_ENABLED"):
    INSTALLED_APPS = INSTALLED_APPS + ("djangosaml2",)  # type: ignore

SOCIAL_AUTH_POSTGRES_JSONFIELD = (
        "DATABASES" in local_settings
        and local_settings["DATABASES"]["default"]["ENGINE"]
        == "django.db.backends.postgresql")

# }}}

# {{{ django: middleware

MIDDLEWARE = (
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "course.auth.ImpersonateMiddleware",
    "course.utils.FacilityFindingMiddleware",
    "course.exam.ExamFacilityMiddleware",
    "course.exam.ExamLockdownMiddleware",
    "relate.utils.MaintenanceMiddleware",
    "social_django.middleware.SocialAuthExceptionMiddleware",
)

# }}}

# {{{ django: auth

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = (
    "course.auth.EmailedTokenBackend",
    "course.auth.APIBearerTokenBackend",
    "course.exam.ExamTicketBackend",
    "django.contrib.auth.backends.ModelBackend",
    )

if local_settings.get("RELATE_SIGN_IN_BY_SAML2_ENABLED"):
    AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + (  # type: ignore
            "djangosaml2.backends.Saml2Backend",
            )

if local_settings.get("RELATE_SOCIAL_AUTH_BACKENDS"):
    AUTHENTICATION_BACKENDS = (
            AUTHENTICATION_BACKENDS
            + local_settings["RELATE_SOCIAL_AUTH_BACKENDS"])

SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",

    "course.auth.social_auth_check_domain_against_blacklist",

    # /!\ Assumes that providers only provide verified emails
    "social_core.pipeline.social_auth.associate_by_email",

    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",

    "course.auth.social_set_user_email_verified",
)

SOCIAL_AUTH_ADMIN_USER_SEARCH_FIELDS = [
        "username", "first_name", "last_name", "email"]

LOGIN_ERROR_URL = "/"

# }}}

# {{{ django-npm

STATICFILES_FINDERS = tuple(STATICFILES_FINDERS) + (
    "npm.finders.NpmFinder",
    )

CODEMIRROR_PATH = "codemirror"

# }}}

ROOT_URLCONF = "relate.urls"

CRISPY_FAIL_SILENTLY = False

WSGI_APPLICATION = "relate.wsgi.application"

# {{{ context processors

RELATE_EXTRA_CONTEXT_PROCESSORS = (
            "relate.utils.settings_context_processor",
            "course.auth.impersonation_context_processor",
            "course.views.fake_time_context_processor",
            "course.views.pretend_facilities_context_processor",
            "course.exam.exam_lockdown_context_processor",

            "social_django.context_processors.backends",
            "social_django.context_processors.login_redirect",
            )

# }}}

# {{{ templates

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
            "builtins": ["course.templatetags.coursetags"],
            }
    },
]

RELATE_OVERRIDE_TEMPLATES_DIRS = (
    local_settings.get("RELATE_OVERRIDE_TEMPLATES_DIRS", []))
if RELATE_OVERRIDE_TEMPLATES_DIRS:
    TEMPLATES[0]["DIRS"] = (
        tuple(RELATE_OVERRIDE_TEMPLATES_DIRS) + TEMPLATES[0]["DIRS"])   # type: ignore  # noqa

# }}}

# {{{ database

# default, likely overriden by local_settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

# }}}

# {{{ internationalization

LANGUAGE_CODE = "en-us"

USE_I18N = True

USE_L10N = True

USE_TZ = True

# }}}

LOGIN_URL = "relate-sign_in_choice"

# Do not remove this setting. It is used by djangosaml2 to determine where to
# redirect after a successful login.
LOGIN_REDIRECT_URL = "/"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/

# {{{ static

STATICFILES_DIRS = (
        join(BASE_DIR, "relate", "static"),
        )

STATIC_URL = "/static/"

STATIC_ROOT = join(BASE_DIR, "static")

# local select2 "static" resources instead of from CDN
# https://goo.gl/dY6xf7
SELECT2_JS = "select2/dist/js/select2.min.js"
SELECT2_CSS = "select2/dist/css/select2.css"

# }}}

SESSION_COOKIE_NAME = "relate_sessionid"
SESSION_COOKIE_AGE = 12096000  # 20 weeks

# {{{ app defaults

RELATE_FACILITIES = {}  # type: Union[None,Dict[str, Dict[str, Any]], Callable[..., Dict[str, Dict[str, Any]]], ]  # noqa

RELATE_TICKET_MINUTES_VALID_AFTER_USE = 0

RELATE_CACHE_MAX_BYTES = 32768

RELATE_ADMIN_EMAIL_LOCALE = "en-us"

RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION = True

RELATE_SIGN_IN_BY_USERNAME_ENABLED = True
RELATE_SHOW_INST_ID_FORM = True
RELATE_SHOW_EDITOR_FORM = True

# }}}

for name, val in local_settings.items():
    if not name.startswith("_"):
        globals()[name] = val

RELATE_SITE_NAME = gettext_noop("RELATE")
RELATE_CUTOMIZED_SITE_NAME = local_settings.get("RELATE_CUTOMIZED_SITE_NAME")
if RELATE_CUTOMIZED_SITE_NAME is not None and RELATE_CUTOMIZED_SITE_NAME.strip():
    RELATE_SITE_NAME = RELATE_CUTOMIZED_SITE_NAME

# {{{ celery config

if "CELERY_BROKER_URL" not in globals():
    from warnings import warn
    warn("CELERY_BROKER_URL not set in local_settings.py: defaulting to amqp://. "
            "If there is no queue server installed, long-running tasks will "
            "appear to hang.")

    CELERY_BROKER_URL = "amqp://"

CELERY_ACCEPT_CONTENT = ["pickle", "json"]
CELERY_TASK_SERIALIZER = "pickle"
# (pickle is buggy in django-celery-results 1.0.1)
# https://github.com/celery/django-celery-results/issues/50
CELERY_RESULT_SERIALIZER = "json"
CELERY_TRACK_STARTED = True

if "CELERY_RESULT_BACKEND" not in globals():
    if (
            "CACHES" in globals()
            and "LocMem" not in CACHES["default"]["BACKEND"]  # type:ignore # noqa
            and "Dummy" not in CACHES["default"]["BACKEND"]  # type:ignore # noqa
            ):
        # If possible, we would like to use an external cache as a
        # result backend--because then the progress bars work, because
        # the writes realizing them arent't stuck inside of an ongoing
        # transaction. But if we're using the in-memory cache, using
        # cache as a results backend doesn't make much sense.

        CELERY_RESULT_BACKEND = "django-cache"

    else:
        CELERY_RESULT_BACKEND = "django-db"

# }}}

LOCALE_PATHS = (
    BASE_DIR + "/locale",
)

# {{{ saml2

# This makes SAML2 logins compatible with (and usable at the same time as)
# email-based logins.
SAML_DJANGO_USER_MAIN_ATTRIBUTE = "username"

SAML_CREATE_UNKNOWN_USER = True

# }}}

# vim: foldmethod=marker
