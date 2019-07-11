#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

# This script (for now) is only intended to install the 'relate' content helper
# script. Its use is not needed for (and unrelated to) deploying RELATE as a
# web service.

# Use 'pip install -r requirements.txt' to install prerequisites for RELATE as
# a web service.

setup(name="relate-courseware",
      version="2016.1",
      description="RELATE courseware",
      long_description=open("README.rst", "rt").read(),

      scripts=["bin/relate"],
      author="Andreas Kloeckner",
      url="https://github.com/inducer/relate",
      author_email="inform@tiker.net",
      license="MIT",
      packages=find_packages(exclude=['tests']),
      install_requires=[
          "django>=2.1.10",
          "django-crispy-forms>=1.5.1",
          "colorama",
          "markdown<3.0",
          "dulwich",
          "pyyaml",
          "nbconvert>=5.2.1",

          # Try to avoid https://github.com/Julian/jsonschema/issues/449
          "attrs>=19",

          "pymbolic",
          "sympy",
          ],
      package_data={
          "relate": [
              "templates/*.html",
              ],
          "course": [
              "templates/course/*.html",
              "templates/course/jinja2/*.tpl",
              ],
          },
      )
