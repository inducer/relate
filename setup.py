#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

# This script really only installs the validation script,
# relate-validate. Its use is not needed (and indeed not recommended)
# for deploying RELATE as a web service.

# Use 'pip install -r requirements.txt' first to install prerequisites.

setup(name="relate-validation",
      version="2015.1",
      description="Installer for the RELATE validation script",

      scripts=["bin/relate-validate"],
      author="Andreas Kloeckner",
      url="https://github.com/inducer/relate",
      author_email="inform@tiker.net",
      license="MIT",
      packages=["relate", "course"])
