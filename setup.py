#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

# This script really only installs the validation script,
# cf-validate. Its use is not needed (and indeed not recommended)
# for deploying CourseFlow as a web service.

setup(name="courseflow-validation",
      version="2014.1",
      description="Installer for the CourseFlow validation script",

      scripts=["bin/cf-validate"],
      author="Andreas Kloeckner",
      url="https://github.com/inducer/courseflow",
      author_email="inform@tiker.net",
      license="MIT",
      packages=["courseflow", "course"])
