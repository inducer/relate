"""
Django settings for courseflow project.

For more information on this file, see
https://docs.djangoproject.com/en/dev/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/dev/ref/settings/
"""

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
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'course',
    'crispy_forms',
)

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

ROOT_URLCONF = 'courseflow.urls'

WSGI_APPLICATION = 'courseflow.wsgi.application'

CRISPY_TEMPLATE_PACK = "bootstrap3"

TEMPLATE_DIRS = (
        join(BASE_DIR, "courseflow", "templates"),
        )

STATICFILES_DIRS = (
        join(BASE_DIR, "courseflow", "static"),
        )

# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

# default, likely overriden by local_settings below
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Internationalization
# https://docs.djangoproject.com/en/dev/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/

STATIC_URL = '/static/'

SESSION_COOKIE_NAME = 'expensely_sessionid'
SESSION_COOKIE_AGE = 12096000 # 20 weeks

for name, val in local_settings.iteritems():
    if not name.startswith("_"):
        globals()[name] = val
