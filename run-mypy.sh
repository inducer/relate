#! /bin/bash

mypy \
  --fast-parser \
  --strict-optional \
  --silent-imports \
  --disallow-untyped-calls \
  relate course
  # --disallow-untyped-defs \
