#! /bin/bash

set -x
set -eo pipefail

# {{{ security

# 38678: django-celery-results: no update currently available
# https://github.com/celery/django-celery-results/issues/154
# 39253:  py.path.svnwc DOS
# 39535:
#   https://github.com/inducer/relate/pull/779
#   amounts to pysaml2 >= 6.5.1 version bump, done in pyproject.toml
# 40291: affects pip, not related to relate's safety
# code not used
# 41002: coverage doesn't affect Relate's security as a web app
poetry run safety check \
        -i 38678 \
        -i 39253 \
        -i 39535 \
        -i 40291 \
        -i 41002 \
        --full-report

# }}}

CODE_DIRS=(relate course accounts)

# FIXME: Also use https://semgrep.dev/p/owasp-top-ten
poetry run semgrep --config "p/ci" "${CODE_DIRS[@]}"

poetry run bandit -r -c pyproject.toml "${CODE_DIRS[@]}"

# vim: foldmethod=marker
