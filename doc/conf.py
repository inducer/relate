import os
import sys
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
    "python": ("https://docs.python.org/3/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "django": (
        "https://docs.djangoproject.com/en/dev/",
        "https://docs.djangoproject.com/en/dev/_objects/",
    ),
    "sympy": ("https://docs.sympy.org/latest", None),

    # https://github.com/dulwich/dulwich/issues/913 (a recurrence)
    "dulwich": (
        # "https://www.dulwich.io/docs/",
        "https://tiker.net/pub/dulwich-docs-stopgap/",
    None),
}

copyright = u"2014-21, Andreas Kloeckner"

version = "2021.1"
release = version
