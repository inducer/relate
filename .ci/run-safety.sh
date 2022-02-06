#! /bin/bash
# 38678: django-celery-results: no update currently available
# https://github.com/celery/django-celery-results/issues/154
# 39253:  py.path.svnwc DOS
# 39535:
#   https://github.com/inducer/relate/pull/779
#   amounts to pysaml2 >= 6.5.1 version bump, done in pyproject.toml
# 40291: affects pip, not related to relate's safety
# code not used
# 41002: coverage doesn't affect Relate's security as a web app
# 4471{5,6,7}: We're not using numpy in a user-exposed-manner.
poetry run safety check \
        -i 38678 \
        -i 39253 \
        -i 39535 \
        -i 40291 \
        -i 41002 \
        -i 44715 \
        -i 44716 \
        -i 44717 \
        --full-report
