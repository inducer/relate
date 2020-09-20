#! /bin/bash

mypy \
  --strict-optional \
  --ignore-missing-imports \
  --follow-imports=skip \
  --disallow-untyped-calls \
  relate course
  # --disallow-untyped-defs \
