# See https://docs.djangoproject.com/en/dev/howto/deployment/checklist/

import os, platform
from os.path import join
BASE_DIR = os.path.dirname(__file__)

# Choose the allowed ways of signing in to RELATE
RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
RELATE_REGISTRATION_ENABLED = True
RELATE_SIGN_IN_BY_EXAM_TICKETS_ENABLED = True
RELATE_SIGN_IN_BY_SAML2_ENABLED = False  # not yet implemented


SECRET_KEY = 'learningub3p49i*4@x$kv6w38e5v$i8!ezq)@*i6z)hdw)gx32-gq*%%zwhat'

ALLOWED_HOSTS = [
        '.learningwhat.com',
        ]


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'relate',
        'USER': 'ifaint',
        'PASSWORD': 'ifaint210',
        'HOST': '',
        'PORT': '5432',
    }
}


BOWER_INSTALLED_APPS = (
    #"django-ckeditor",
    #"pdf.js=https://github.com/mozilla/pdf.js/releases/download/v1.1.215/pdfjs-1.1.215-dist.zip",
    "jquery-file-upload",
    "blueimp-gallery",
    #"html5shiv",
    )


# Recommended, because dulwich is kind of slow in retrieving stuff.
#
CACHES = {
   'default': {
     'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
     'LOCATION': '127.0.0.1:11211',
   }
 }

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
TEMPLATE_DEBUG = DEBUG

# Your course git repositories will be stored under this directory.
# Make sure it's writable by your web user.
#
# The default below makes them sit side-by-side with your relate checkout,
# which makes sense for development, but you probably want to change this
# in production.
#
# The 'course identifiers' you enter will be directory names below this root.

GIT_ROOT = "/srv/www/relate/course-git"

EMAIL_USE_TLS = True
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_HOST_USER = 'webmaster@learningwhat.com'
EMAIL_HOST_PASSWORD = 'ifaint210'
EMAIL_PORT = 587
DEFAULT_FROM_EMAIL = 'webmaster@learningwhat.com'

ROBOT_EMAIL_FROM = 'LearningWhat Webmaster <webmaster@learningwhat.com>'

SERVER_EMAIL = ROBOT_EMAIL_FROM

ADMINS = (
  ("LearningWhat Webmaster", "webmaster@learningwhat.com"),
  )
  
LANGUAGE_CODE = 'zh_CN'
#LANGUAGE_CODE = 'en-us'

RELATE_ADMIN_EMAIL_LOCALE = "zh_CN"

# Cool down time (seconds) required before another new session of a flow
# is allowed to be started.
RELATE_SESSION_RESTART_COOLDOWN_SECONDS = 10

#TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

TIME_ZONE = 'Hongkong'

FORMAT_MODULE_PATH = ['formats']

STUDENT_SIGN_IN_VIEW = "relate-sign_in_by_user_pw"
#STUDENT_SIGN_IN_VIEW = "relate-sign_in_by_email"

# A string containing the image ID of the docker image to be used to run
# student Python code. Docker should download the image on first run.
RELATE_DOCKER_RUNPY_IMAGE = "inducer/relate-runpy-i386"

RELATE_MAINTENANCE_MODE = False

# See https://docs.djangoproject.com/en/dev/ref/templates/builtins/#date
# to build your own format of short datetime format of your language.
if LANGUAGE_CODE == 'zh_CN':
    RELATE_SHORT_DATE_TIME_FORMAT = 'M/D HH:mm'
else:
    RELATE_SHORT_DATE_TIME_FORMAT = 'short'
    
SENDFILE_URL = '/protected'

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = '/media/'

#CKEDITOR_UPLOAD_PATH = os.path.join(MEDIA_ROOT, "content", "ck_upload")

if "Windows" in platform.system():
    ALLOWED_HOSTS = [
        '*',
        ]
    DEBUG = True
    TEMPLATE_DEBUG = DEBUG
    LANGUAGE_CODE = 'zh_CN'
    GIT_ROOT = r"D:\document\python\course\course-git"
    
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    
    SENDFILE_BACKEND = 'sendfile.backends.development'

    SENDFILE_ROOT = os.path.join(BASE_DIR, 'protected')
    

    
#    EMAIL_USE_SSL = True
#    EMAIL_HOST = 'smtp.ym.163.com'
#    EMAIL_HOST_USER = 'webmaster@learningwhat.com'
#    EMAIL_HOST_PASSWORD = 'icom210'
#    EMAIL_PORT = 25
#    DEFAULT_FROM_EMAIL = 'webmaster@learningwhat.com'
#
#    ROBOT_EMAIL_FROM = 'LearningWhat Webmaster <webmaster@learningwhat.com>'
#
#    SERVER_EMAIL = ROBOT_EMAIL_FROM
#
#    ADMINS = (
#      ("LearningWhat Webmaster", "webmaster@learningwhat.com"),
#      )
    EMAIL_USE_TLS = True
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_HOST_USER = 'webmaster@learningwhat.com'
    EMAIL_HOST_PASSWORD = 'ifaint210'
    DEFAULT_FROM_EMAIL = 'webmaster@learningwhat.com'
    ROBOT_EMAIL_FROM = 'LearningWhat Webmaster<webmaster@learningwhat.com>'


    SERVER_EMAIL = ROBOT_EMAIL_FROM

    ADMINS = (
      ("LearningWhat Webmaster", "webmaster@learningwhat.com"),
      )
    
else:

    SENDFILE_BACKEND = 'sendfile.backends.nginx'
    SENDFILE_ROOT = "/srv/www/relate/protected"
    SENDFILE_URL = '/protected'
    STATIC_ROOT = "/srv/www/relate/static"

    
