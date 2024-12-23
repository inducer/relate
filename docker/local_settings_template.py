# See https://docs.djangoproject.com/en/dev/howto/deployment/checklist/

import os.path as path
import os

_BASEDIR = path.dirname(path.abspath(__file__))

# {{{ database and site

# TODO: Need to find out WHY this needs to be set in production - and ensure its set from a secret - so it stays the same
SECRET_KEY = "<CHANGE ME TO SOME RANDOM STRING ONCE IN PRODUCTION>"

ALLOWED_HOSTS = [ $EXTRAHOSTS ]

CSRF_TRUSTED_ORIGINS = [ $ORIGINS ]

# Configure the following as url as above.
RELATE_BASE_URL = "https://relate.obmondo.com"

from django.utils.translation import gettext_noop  # noqa

# Uncomment this to configure the site name of your relate instance.
# If not configured, "RELATE" will be used as default value.
# Use gettext_noop() if you want it to be discovered as an i18n literal
# for translation.
#RELATE_CUTOMIZED_SITE_NAME = gettext_noop("My RELATE")

# Uncomment this to use a real database. If left commented out, a local SQLite3
# database will be used, which is not recommended for production use.
#
DATABASES = {
     "default": {
         "ENGINE": "django.db.backends.postgresql",
         "NAME": "relate",
         "USER": "$DBUSER",
         "PASSWORD": '$DBPASS',
         "HOST": '$DBHOST',
         "PORT": '5432',
     }
 }

# Recommended, because dulwich is kind of slow in retrieving stuff.
#
# Also, progress bars for long-running operations will only work
# properly if you enable this. (or a similar out-of-process cache
# backend)
#
# You must 'pip install pylibmc' to use this (which in turn may require
# installing 'libmemcached-dev').
#
# Btw, do not be tempted to use 'MemcachedCache'--it's unmaintained and
# broken in Python 33, as of 2016-08-01.
#
# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.memcached.PyLibMCCache",
#         "LOCATION": '127.0.0.1:11211',
#     }
# }

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

TIME_ZONE = "Europe/Copenhagen"

# RELATE needs a message broker for long-running tasks.
#
# See here for options:
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#broker-url
#
# The dev server will run fine without this, but any tasks that require
# queueing will just appear to hang. On Debian/Ubuntu, the following line
# should be enough to satisfy this requirement.
#
# apt-get install rabbitmq-server
CELERY_BROKER_URL = "amqp://rabbitmq"

# }}}

# {{{ git storage

# Your course git repositories will be stored under this directory.
# Make sure it's writable by your web user.
#
# The "course identifiers" you enter will be directory names below this root.

#GIT_ROOT = "/some/where"
GIT_ROOT = path.join(_BASEDIR, "git-roots")

# }}}

# {{{ bulk storage

from django.core.files.storage import FileSystemStorage
# This must be a subclass of django.core.storage.Storage.
# This should *not* be MEDIA_ROOT, and the corresponding directory/storage location
# should *not* be accessible under a URL.
RELATE_BULK_STORAGE = FileSystemStorage(path.join(_BASEDIR, "bulk-storage"))

# }}}

# {{{ email

EMAIL_HOST = "$SMTPHOST"
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
EMAIL_PORT = $SMTPPORT
EMAIL_USE_TLS = False

ROBOT_EMAIL_FROM = "Klavs Klavsen <klavs@enableit.dk>"
RELATE_ADMIN_EMAIL_LOCALE = "en_US"

SERVER_EMAIL = ROBOT_EMAIL_FROM

ADMINS = (
    ("Klavs Klavsen", "klavs@enableit.dk"),
    )

# If your email service do not allow nonauthorized sender, uncomment the following
# statement and change the configurations above accordingly, noticing that all
# emails will be sent using the EMAIL_ settings above.
#RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER = False

# Advanced email settings if you want to configure multiple SMTPs for different
# purpose/type of emails. It is also very useful when
# "RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER" is False.
# If you want to enable this functionality, set the next line to True, and edit
# the next block with your cofigurations.
RELATE_ENABLE_MULTIPLE_SMTP = False

if RELATE_ENABLE_MULTIPLE_SMTP:
    EMAIL_CONNECTIONS = {

        # For automatic email sent by site.
        "robot": {
            # You can use your preferred email backend.
            "backend": "djcelery_email.backends.CeleryEmailBackend",
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },

        # For emails that expect no reply for recipients, e.g., registration,
        # reset password, etc.
        "no_reply": {
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },

        # For sending notifications like submission of flow sessions.
        "notification": {
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },

        # For sending feedback email to students in grading interface.
        "grader_feedback": {
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },

        # For student to send email to course staff in flow pages
        "student_interact": {
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },

        # For enrollment request email sent to course instructors
        "enroll": {
            "host": "smtp.gmail.com",
            "username": "blah@blah.com",
            "password": "password",
            "port": 587,
            "use_tls": True,
        },
    }

    # This will be used as default connection when other keys are not set.
    EMAIL_CONNECTION_DEFAULT = "robot"

    NO_REPLY_EMAIL_FROM = "Noreply <noreply_example@enableit.dk>"
    NOTIFICATION_EMAIL_FROM = "Notification <notification_example@enableit.dk>"
    GRADER_FEEDBACK_EMAIL_FROM = "Feedback <feedback_example@enableit.dk>"
    STUDENT_INTERACT_EMAIL_FROM = "interaction <feedback_example@enableit.dk>"
    ENROLLMENT_EMAIL_FROM = "Enrollment <enroll@enableit.dk>"


# }}}


# Cool down time (seconds) required before another new session of a flow
# is allowed to be started.
RELATE_SESSION_RESTART_COOLDOWN_SECONDS = 10


# {{{ sign-in methods

RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
RELATE_SIGN_IN_BY_USERNAME_ENABLED = True
RELATE_REGISTRATION_ENABLED = False
RELATE_SIGN_IN_BY_EXAM_TICKETS_ENABLED = False

# If you enable this, you must also have saml_config.py in this directory.
# See saml_config.py.example for help.
RELATE_SIGN_IN_BY_SAML2_ENABLED = False

RELATE_SOCIAL_AUTH_BACKENDS = (
        # See https://python-social-auth.readthedocs.io/en/latest/
        # for full list.
        'social_core.backends.keycloak.KeycloakOAuth2',
        'django.contrib.auth.backends.ModelBackend',
        # CAUTION: Relate uses emails returned by the backend to match
        # users. Only use backends that return verified emails.
        )

# you can configure your social auth by referencing this https://python-social-auth.readthedocs.io/en/latest/backends/ 
# we configured it for keyclaok as a demo
SOCIAL_AUTH_KEYCLOAK_ID_KEY = 'email'
SOCIAL_AUTH_KEYCLOAK_PUBLIC_KEY= os.environ.get('KEYCLOAK_PUBLICKEY')
SOCIAL_AUTH_KEYCLOAK_KEY = 'relate'  
SOCIAL_AUTH_KEYCLOAK_SECRET = os.environ.get('KEYCLOAK_SECRET')
SOCIAL_AUTH_KEYCLOAK_SERVER_URL = 'https://<need-to-update-hostname>/realms/test-relate/'  # required to fill
SOCIAL_AUTH_KEYCLOAK_AUTHORIZATION_URL = \
    'https://<need-to-update-hostname>/auth/realms/test-relate/protocol/openid-connect/auth' # required to fill
SOCIAL_AUTH_KEYCLOAK_ACCESS_TOKEN_URL = \
    'https://<need-to-update-hostname>/auth/realms/test-relate/protocol/openid-connect/token' # required to fill
SOCIAL_AUTH_REDIRECT_IS_HTTPS = True
SOCIAL_AUTH_SESSION_EXPIRATION = True



# Set the "SOCIAL_AUTH_LOGIN_REDIRECT_URL" to a page you want to redirect to after login
# SOCIAL_AUTH_LOGIN_REDIRECT_URL = 'https://relate.kbm.obmondo.com/social-auth/complete/keycloak/'
# When registering your OAuth2 app (and consent screen) with Google,
# specify the following authorized redirect URI:
# https://sitename.edu/social-auth/complete/google-oauth2/

# Blacklist these domains for social auth. This may be useful if there
# is a canonical way (e.g. SAML2) for members of that domain to
# sign in.
# RELATE_SOCIAL_AUTH_BLACKLIST_EMAIL_DOMAINS = {
#   "illinois.edu": "Must use SAML2 to sign in."
#   }

# }}}

# {{{ editable institutional id before verification?

# If set to False, user won't be able to edit institutional ID
# after submission. Set to False only when you trust your students
# or you don't want to verfiy insitutional ID they submit.
RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION = True

# If set to False, these fields will be hidden in the user profile form.
RELATE_SHOW_INST_ID_FORM = True
RELATE_SHOW_EDITOR_FORM = True

# }}}

# Whether disable "markdown.extensions.codehilite" when rendering page markdown.
# Default to True, as enable it sometimes crashes for some pages with code fences.
# For this reason, there will be a warning when the attribute is set to False when
# starting the server.
#RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION = True

# {{{ user full_name format

# RELATE's default full_name format is "'%s %s' % (first_name, last_name)",
# you can override it by supply a customized method/fuction, with
# "firstname" and "lastname" as its paramaters, and return a string.

# For example, you can define it like this:

#<code>
#   def my_fullname_format(firstname, lastname):
#         return "%s%s" % (last_name, first_name)
#</code>

# and then uncomment the following line and enable it with:

#RELATE_USER_FULL_NAME_FORMAT_METHOD = my_fullname_format

# You can also import it from your custom module, or use a dotted path of the
# method, i.e.:
#RELATE_USER_FULL_NAME_FORMAT_METHOD = "path.to.my_fullname_format"

# }}}

# {{{ system email appellation priority

# RELATE's default email appellation of the receiver is a ordered list:
# ["first_name", "email", "username"], when first_name is not None
# (e.g, first_name = "Foo"), the email will be opened
# by "Dear Foo,". If first_name is None, then email will be used
# as appellation, so on and so forth.

# you can override the appellation priority by supply a customized list
# named relate_email_appellation_priority_list. The available
# elements include first_name, last_name, get_full_name, email and
# username.

# RELATE_EMAIL_APPELLATION_PRIORITY_LIST = [
#         "full_name", "first_name", "email", "username"]

# }}}

# {{{ custom method for masking user profile
# When a participation, for example, teaching assistant, has limited access to
# students' profile (i.e., has_permission(pperm.view_participant_masked_profile)),
# a built-in mask method (which is based on pk of user instances) is used be
# default. The mask method can be overriden by the following a custom method, with
# user as the args.

#RELATE_USER_PROFILE_MASK_METHOD = "path.tomy_method
# For example, you can define it like this:

#<code>
#   def my_mask_method(user):
#         return "User_%s" % str(user.pk + 100)
#</code>

# and then uncomment the following line and enable it with:

#RELATE_USER_PROFILE_MASK_METHOD = my_mask_method

# You can also import it from your custom module, or use a dotted path of the
# method, i.e.:
#RELATE_USER_PROFILE_MASK_METHOD = "path.to.my_mask_method"

# }}}

# {{{ extra checks

# This allow user to add customized startup checkes for user-defined modules
# using Django's system checks (https://docs.djangoproject.com/en/dev/ref/checks/)
# For example, define a `my_check_func in `my_module` with
# <code>
#   def my_check_func(app_configs, **kwargs):
#         return [list of error]
#</code>
# The configuration should be
# RELATE_STARTUP_CHECKS_EXTRA = ["my_module.my_check_func"]
# i.e., Each item should be the path to an importable check function.
#RELATE_STARTUP_CHECKS_EXTRA = []

# }}}

# {{{ overriding built-in templates
# Uncomment the following to enable templates overriding. It should be configured
# as a list/tuple of path(s).
# For example, if you the templates are in a folder named "my_templates" in the
# root dir of the project, with base.html (project template), course_base.html,
# and sign-in-email.txt (app templates) etc., are the templates you want to
# override, the structure of the files should look like:
#    ...
#    relate/
#    local_settings.py
#    my_templates/
#        base.html
#        ...
#        course/
#            course_base.html
#            sign-in-email.txt
#                ...
#

# import os.path
# RELATE_OVERRIDE_TEMPLATES_DIRS = [
#       os.path.join(os.path.dirname(__file__), "my_templates"),
#       os.path.join(os.path.dirname(__file__), "my_other_templates")
# ]

# }}}

# {{{ docker

# A string containing the image ID of the docker image to be used to run
# student Python code. Docker should download the image on first run.
RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runcode-python-amd64"
# RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runpy-amd64-tensorflow"
# (bigger, but includes TensorFlow)

# A URL pointing to the Docker command interface which RELATE should use
# to spawn containers for student code.
RELATE_DOCKER_URL = "unix://var/run/docker.sock"

RELATE_DOCKER_TLS_CONFIG = None

# Example setup for targeting remote Docker instances
# with TLS authentication:

# RELATE_DOCKER_URL = "https://relate.cs.illinois.edu:2375"
#
# import os.path
# pki_base_dir = os.path.dirname(__file__)
#
# import docker.tls
# RELATE_DOCKER_TLS_CONFIG = docker.tls.TLSConfig(
#     client_cert=(
#         os.path.join(pki_base_dir, "client-cert.pem"),
#         os.path.join(pki_base_dir, "client-key.pem"),
#         ),
#     ca_cert=os.path.join(pki_base_dir, "ca.pem"),
#     verify=True)

# }}}

# {{{ maintenance and announcements

RELATE_MAINTENANCE_MODE = False

RELATE_MAINTENANCE_MODE_EXCEPTIONS = []
# RELATE_MAINTENANCE_MODE_EXCEPTIONS = ["192.168.1.0/24"]

# May be set to a string to set a sitewide announcement visible on every page.
RELATE_SITE_ANNOUNCEMENT = None

# }}}

# Uncomment this to enable i18n, change "en-us" to locale name your language.
# Make sure you have generated, translate and compile the message file of your
# language. If commented, RELATE will use default language "en-us".

#LANGUAGE_CODE = "en-us"

# You can (and it's recommended to) override Django's built-in LANGUAGES settings
# if you want to filter languages allowed for course-specific languages.
# The format of languages should be a list/tuple of 2-tuples:
# (language_code, language_description). If there are entries with the same
# language_code, language_description will be using the one which comes latest.
#.If LANGUAGES is not configured, django.conf.global_settings.LANGUAGES will be
# used.
# Note: make sure LANGUAGE_CODE you used is also in LANGUAGES, if it is not
# the default "en-us". Otherwise translation of that language will not work.

# LANGUAGES = [
#     ("en", "English"),
#     ("zh-hans", "Simplified Chinese"),
#     ("de", "German"),
# ]

# {{{ exams and testing

# This may also be a callable that receives a local-timezone datetime and returns
# an equivalent dictionary.
#
# def RELATE_FACILITIES(now_datetime):
#     from relate.utils import localize_datetime
#     from datetime import datetime
#
#     if (now_datetime >= localize_datetime(datetime(2016, 5, 5, 0, 0))
#             and now_datetime < localize_datetime(datetime(2016, 5, 6, 0, 0))):
#         ip_ranges = [
#             "127.0.0.1/32",
#             "192.168.77.0/24",
#             ]
#     else:
#         ip_ranges = []
#
#     return {
#         "test_center": {
#             "ip_ranges": ip_ranges,
#             "exams_only": True,
#             },
#     }


RELATE_FACILITIES = {
    "test_center": {
        "ip_ranges": [
            "192.168.192.0/24",
            ],
        "exams_only": False,
    },
}

# For how many minutes is an exam ticket still usable for login after its first
# use?
RELATE_TICKET_MINUTES_VALID_AFTER_USE = 12*60

# }}}

# {{{ saml2 (optional)

if RELATE_SIGN_IN_BY_SAML2_ENABLED:
    from os import path
    import saml2.saml
    _BASE_URL = "https://relate.cs.illinois.edu"

    # see saml2-keygen.sh in this directory
    _SAML_KEY_FILE = path.join(_BASEDIR, "saml-config", "sp-key.pem")
    _SAML_CERT_FILE = path.join(_BASEDIR, "saml-config", "sp-cert.pem")

    SAML_ATTRIBUTE_MAPPING = {
        "eduPersonPrincipalName": ("username",),
        "iTrustUIN": ("institutional_id",),
        "mail": ("email",),
        "givenName": ("first_name", ),
        "sn": ("last_name", ),
    }
    SAML_DJANGO_USER_MAIN_ATTRIBUTE = "username"
    SAML_DJANGO_USER_MAIN_ATTRIBUTE_LOOKUP = "__iexact"

    saml_idp = {
        # Find the entity ID of your IdP and make this the key here:
        "urn:mace:incommon:uiuc.edu": {
            "single_sign_on_service": {
                # Add the POST and REDIRECT bindings for the sign on service here:
                saml2.BINDING_HTTP_POST:
                    "https://shibboleth.illinois.edu/idp/profile/SAML2/POST/SSO",
                saml2.BINDING_HTTP_REDIRECT:
                    "https://shibboleth.illinois.edu/idp/profile/SAML2/Redirect/SSO",
                },
            "single_logout_service": {
                # And the REDIRECT binding for the logout service here:
                saml2.BINDING_HTTP_REDIRECT:
                "https://shibboleth.illinois.edu/idp/logout.jsp",  # noqa
                },
            },
        }

    SAML_CONFIG = {
        # full path to the xmlsec1 binary programm
        "xmlsec_binary": "/usr/bin/xmlsec1",

        # your entity id, usually your subdomain plus the url to the metadata view
        # (usually no need to change)
        "entityid": _BASE_URL + "/saml2/metadata/",

        # directory with attribute mapping
        # (already populated with samples from djangosaml2, usually no need to
        # change)
        "attribute_map_dir": path.join(_BASEDIR, "saml-config", "attribute-maps"),

        "allow_unknown_attributes": True,

        # this block states what services we provide
        "service": {
            "sp": {
                "name": "RELATE SAML2 SP",

                # Django sets SameSite attribute on session cookies,
                # which causes problems. Work around that, for now.
                # https://github.com/peppelinux/djangosaml2/issues/143#issuecomment-633694504
                "allow_unsolicited": True,

                "name_id_format": saml2.saml.NAMEID_FORMAT_TRANSIENT,
                "endpoints": {
                    # url and binding to the assertion consumer service view
                    # do not change the binding or service name
                    "assertion_consumer_service": [
                        (_BASE_URL + "/saml2/acs/",
                         saml2.BINDING_HTTP_POST),
                        ],
                    # url and binding to the single logout service view
                    # do not change the binding or service name
                    "single_logout_service": [
                        (_BASE_URL + "/saml2/ls/",
                         saml2.BINDING_HTTP_REDIRECT),
                        (_BASE_URL + "/saml2/ls/post",
                         saml2.BINDING_HTTP_POST),
                        ],
                    },

                # attributes that this project needs to identify a user
                "required_attributes": ["uid"],

                # attributes that may be useful to have but not required
                "optional_attributes": ["eduPersonAffiliation"],

                "idp": saml_idp,
                },
            },

        # You will get this XML file from your institution. It has finite validity
        # and will need to be re-downloaded periodically.
        #
        # "itrust" is an example name that's valid for the University of Illinois.
        # This particular file is public and lives at
        # https://discovery.itrust.illinois.edu/itrust-metadata/itrust-metadata.xml

        "metadata": {
            "local": [path.join(_BASEDIR, "saml-config", "itrust-metadata.xml")],
            },

        # set to 1 to output debugging information
        "debug": 1,

        # certificate and key
        "key_file": _SAML_KEY_FILE,
        "cert_file": _SAML_CERT_FILE,

        "encryption_keypairs": [
                {
                    "key_file": _SAML_KEY_FILE,
                    "cert_file": _SAML_CERT_FILE,
                    }
                ],

        # own metadata settings
        "contact_person": [
            {"given_name": "Andreas",
             "sur_name": "Kloeckner",
             "company": "CS - University of Illinois",
             "email_address": "andreask@illinois.edu",
             "contact_type": "technical"},
            {"given_name": "Andreas",
             "sur_name": "Kloeckner",
             "company": "CS - University of Illinois",
             "email_address": "andreask@illinois.edu",
             "contact_type": "administrative"},
            ],
        # you can set multilanguage information here
        "organization": {
            "name": [("RELATE", "en")],
            "display_name": [("RELATE", "en")],
            "url": [(_BASE_URL, "en")],
            },
        "valid_for": 24,  # how long is our metadata valid
        }

# }}}

# vim: filetype=python:foldmethod=marker
