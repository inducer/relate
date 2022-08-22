#! /bin/bash

mypy \
  --strict-optional \
  --show-error-codes \
  --ignore-missing-imports \
  --follow-imports=skip \
  --disallow-untyped-calls \
  relate course
  # --disallow-untyped-defs \
