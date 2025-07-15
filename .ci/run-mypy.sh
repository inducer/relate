#! /bin/bash

uv run --no-dev --group mypy --frozen --isolated \
    mypy relate course accounts prairietest "$@"
