# See https://docs.djangoproject.com/en/dev/howto/deployment/checklist/

# {{{ database and site

SECRET_KEY = '<CHANGE ME TO SOME RANDOM STRING ONCE IN PRODUCTION>'

ALLOWED_HOSTS = [
        "relate.example.com",
        ]

# Configure the following as url as above.
RELATE_BASE_URL = "http://YOUR/RELATE/SITE/DOMAIN"

# Uncomment this to use a real database. If left commented out, a local SQLite3
# database will be used, which is not recommended for production use.
#
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql_psycopg2',
#         'NAME': 'relate',
#         'USER': 'relate',
#         'PASSWORD': '<PASSWORD>',
#         'HOST': '127.0.0.1',
#         'PORT': '5432',
#     }
# }

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
#     'default': {
#         'BACKEND': 'django.core.cache.backends.memcached.PyLibMCCache',
#         'LOCATION': '127.0.0.1:11211',
#     }
# }

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

TIME_ZONE = "America/Chicago"

# }}}

# {{{ git storage

# Your course git repositories will be stored under this directory.
# Make sure it's writable by your web user.
#
# The default below makes them sit side-by-side with your relate checkout,
# which makes sense for development, but you probably want to change this
# in production.
#
# The 'course identifiers' you enter will be directory names below this root.

#GIT_ROOT = "/some/where"
GIT_ROOT = ".."

# }}}

# {{{ email

EMAIL_HOST = '127.0.0.1'
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_PORT = 25
EMAIL_USE_TLS = False

ROBOT_EMAIL_FROM = "Example Admin <admin@example.com>"
RELATE_ADMIN_EMAIL_LOCALE = "en_US"

SERVER_EMAIL = ROBOT_EMAIL_FROM

ADMINS = (
    ("Example Admin", "admin@example.com"),
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
            'backend': 'djcelery_email.backends.CeleryEmailBackend',
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },

        # For emails that expect no reply for recipients, e.g., registration,
        # reset password, etc.
        "no_reply": {
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },

        # For sending notifications like submission of flow sessions.
        "notification": {
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },

        # For sending feedback email to students in grading interface.
        "grader_feedback": {
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },

        # For student to send email to course staff in flow pages
        "student_interact": {
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },
    }

    # This will be used as default connection when other keys are not set.
    EMAIL_CONNECTION_DEFAULT = "robot"

    NO_REPLY_EMAIL_FROM = "Noreply <noreply_example@example.com>"
    NOTIFICATION_EMAIL_FROM = "Notification <notification_example@example.com>"
    GRADER_FEEDBACK_EMAIL_FROM = "Feedback <feedback_example@example.com>"
    STUDENT_INTERACT_EMAIL_FROM = "interaction <feedback_example@example.com>"


# }}}


# Cool down time (seconds) required before another new session of a flow
# is allowed to be started.
RELATE_SESSION_RESTART_COOLDOWN_SECONDS = 10


# {{{ sign-in methods

RELATE_SIGN_IN_BY_EMAIL_ENABLED = True
RELATE_REGISTRATION_ENABLED = False
RELATE_SIGN_IN_BY_EXAM_TICKETS_ENABLED = True

# If you enable this, you must also have saml_config.py in this directory.
# See saml_config.py.example for help.
RELATE_SIGN_IN_BY_SAML2_ENABLED = False

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


# {{{ user full_name format

# RELATE's default full_name format is "'%s %s' % (first_name, last_name)",
# you can override it by supply a customized method/fuction, with
# "firstname" and "lastname" as its paramaters, and return a string.

# For example, you can define it like this:

#<code>
#   def my_fullname_format(firstname, lastname)
#         return "%s%s" % (last_name, first_name)
#</code>

# and then uncomment the following line and enable it with:

#RELATE_USER_FULL_NAME_FORMAT_METHOD = my_fullname_format

# You can also import it from your custom module.

# }}}

# {{{ system email appelation priority

# RELATE's default email appelation of the receiver is a ordered list:
# ["first_name", "email", "username"], when first_name is not None
# (e.g, first_name = "Foo"), the email will be opened
# by "Dear Foo,". If first_name is None, then email will be used
# as appelation, so on and so forth.

# you can override the appelation priority by supply a customized list
# named RELATE_EMAIL_APPELATION_PRIORITY_LIST. The available
# elements include first_name, last_name, get_full_name, email and
# username.

# RELATE_EMAIL_APPELATION_PRIORITY_LIST = [
#         "full_name", "first_name", "email", "username"]

# }}}

# {{{ docker

# A string containing the image ID of the docker image to be used to run
# student Python code. Docker should download the image on first run.
RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runpy-i386"

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

# Uncomment this to enable i18n, change 'en-us' to locale name your language.
# Make sure you have generated, translate and compile the message file of your
# language. If commented, RELATE will use default language 'en-us'.

#LANGUAGE_CODE='en-us'

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
    _BASEDIR = path.dirname(path.abspath(__file__))

    _BASE_URL = 'https://relate.cs.illinois.edu'

    # see saml2-keygen.sh in this directory
    _SAML_KEY_FILE = path.join(_BASEDIR, 'saml-config', 'sp-key.pem')
    _SAML_CERT_FILE = path.join(_BASEDIR, 'saml-config', 'sp-cert.pem')

    SAML_ATTRIBUTE_MAPPING = {
        'eduPersonPrincipalName': ('username',),
        'iTrustUIN': ('institutional_id',),
        'mail': ('email',),
        'givenName': ('first_name', ),
        'sn': ('last_name', ),
    }
    SAML_DJANGO_USER_MAIN_ATTRIBUTE = 'username'
    SAML_DJANGO_USER_MAIN_ATTRIBUTE_LOOKUP = '__iexact'

    SAML_CONFIG = {
        # full path to the xmlsec1 binary programm
        'xmlsec_binary': '/usr/bin/xmlsec1',

        # your entity id, usually your subdomain plus the url to the metadata view
        # (usually no need to change)
        'entityid': _BASE_URL + '/saml2/metadata/',

        # directory with attribute mapping
        # (already populated with samples from djangosaml2, usually no need to
        # change)
        'attribute_map_dir': path.join(_BASEDIR, 'saml-config', 'attribute-maps'),

        'allow_unknown_attributes': True,

        # this block states what services we provide
        'service': {
            'sp': {
                'name': 'RELATE SAML2 SP',
                'name_id_format': saml2.saml.NAMEID_FORMAT_TRANSIENT,
                'endpoints': {
                    # url and binding to the assertion consumer service view
                    # do not change the binding or service name
                    'assertion_consumer_service': [
                        (_BASE_URL + '/saml2/acs/',
                         saml2.BINDING_HTTP_POST),
                        ],
                    # url and binding to the single logout service view
                    # do not change the binding or service name
                    'single_logout_service': [
                        (_BASE_URL + '/saml2/ls/',
                         saml2.BINDING_HTTP_REDIRECT),
                        (_BASE_URL + '/saml2/ls/post',
                         saml2.BINDING_HTTP_POST),
                        ],
                    },

                # attributes that this project needs to identify a user
                'required_attributes': ['uid'],

                # attributes that may be useful to have but not required
                'optional_attributes': ['eduPersonAffiliation'],

                # in this section the list of IdPs we talk to are defined
                'idp': {
                    # Find the entity ID of your IdP and make this the key here:
                    'urn:mace:incommon:uiuc.edu': {
                        'single_sign_on_service': {
                            # Add the POST and REDIRECT bindings for the sign on service here:
                            saml2.BINDING_HTTP_POST:
                                'https://shibboleth.illinois.edu/idp/profile/SAML2/POST/SSO',
                            saml2.BINDING_HTTP_REDIRECT:
                                'https://shibboleth.illinois.edu/idp/profile/SAML2/Redirect/SSO',
                            },
                        'single_logout_service': {
                            # And the REDIRECT binding for the logout service here:
                            saml2.BINDING_HTTP_REDIRECT:
                            'https://shibboleth.illinois.edu/idp/logout.jsp',  # noqa
                            },
                        },
                    },
                },
            },

        # You will get this XML file from your institution. It has finite validity
        # and will need to be re-downloaded periodically.
        #
        # "itrust" is an example name that's valid for the University of Illinois.
        # This particular file is public and lives at
        # https://discovery.itrust.illinois.edu/itrust-metadata/itrust-metadata.xml

        'metadata': {
            'local': [path.join(_BASEDIR, 'saml-config', 'itrust-metadata.xml')],
            },

        # set to 1 to output debugging information
        'debug': 1,

        # certificate and key
        'key_file': _SAML_KEY_FILE,
        'cert_file': _SAML_CERT_FILE,

        'encryption_keypairs': [
                {
                    'key_file': _SAML_KEY_FILE,
                    'cert_file': _SAML_CERT_FILE,
                    }
                ],

        # own metadata settings
        'contact_person': [
            {'given_name': 'Andreas',
             'sur_name': 'Kloeckner',
             'company': 'CS - University of Illinois',
             'email_address': 'andreask@illinois.edu',
             'contact_type': 'technical'},
            {'given_name': 'Andreas',
             'sur_name': 'Kloeckner',
             'company': 'CS - University of Illinois',
             'email_address': 'andreask@illinois.edu',
             'contact_type': 'administrative'},
            ],
        # you can set multilanguage information here
        'organization': {
            'name': [('RELATE', 'en')],
            'display_name': [('RELATE', 'en')],
            'url': [(_BASE_URL, 'en')],
            },
        'valid_for': 24,  # how long is our metadata valid
        }

# }}}

# vim: filetype=python:foldmethod=marker
