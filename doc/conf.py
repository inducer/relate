import sys
import os
from urllib.request import urlopen

_conf_url = \
        "https://raw.githubusercontent.com/inducer/sphinxconfig/main/sphinxconfig.py"
with urlopen(_conf_url) as _inf:
    exec(compile(_inf.read(), _conf_url, "exec"), globals())

sys.path.insert(0, os.path.abspath(".."))

os.environ["DJANGO_SETTINGS_MODULE"] = "relate.settings"

import django

django.setup()

intersphinx_mapping = {
    "https://docs.python.org/3/": None,
    "https://numpy.org/doc/stable/": None,
    "django": (
        "https://docs.djangoproject.com/en/dev/",
        "https://docs.djangoproject.com/en/dev/_objects/",
    ),
    "https://docs.sympy.org/latest": None,

    # https://github.com/dulwich/dulwich/issues/913
    # "https://www.dulwich.io/docs/": None,
    "https://tiker.net/pub/dulwich-docs-stopgap/": None,
}

copyright = u"2014-21, Andreas Kloeckner"

version = "2021.1"
release = version
