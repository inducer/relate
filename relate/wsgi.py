"""
WSGI config for relate project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/
"""
from __future__ import annotations

import os


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relate.settings")

from django.core.wsgi import get_wsgi_application


application = get_wsgi_application()
