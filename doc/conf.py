from __future__ import annotations

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
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

nitpick_ignore_regex = [
    ("py:class", "course.validation._pydantic_validate.*$"),
    ("py:class", "course.validation.validate_nonempty"),
    ("py:class", "validate_nonempty"),
    ("py:class", "re.compile"),
    ("py:class", "annotated_types.[A-Za-z]+"),
    ("py:class", "PositiveInt"),
    ("py:class", "IdentifierStr"),
    ("py:class", "SerializeAsAny"),
    ("py:class", "AfterValidator"),
    ("py:class", "FileSystemFakeRepo"),
    ("py:class", "pydantic.functional_serializers.SerializeAsAny"),
    ("py:class", "Ge|Le|Gt|Lt|AllowInfNan"),
]

copyright = "2014-21, Andreas Kloeckner"

version = "2021.1"
release = version

sphinxconfig_missing_reference_aliases = {
    "GradeAggregationStrategy": "cls:course.constants.GradeAggregationStrategy",
}


def setup(app):
    app.connect("missing-reference", process_autodoc_missing_reference)  # noqa: F821
