#! /bin/bash
# 38678: django-celery-results: no update currently available
# https://github.com/celery/django-celery-results/issues/154
# 39253:  py.path.svnwc DOS
# code not used
poetry run safety check \
        -i 38678 \
        -i 39253 \
        --full-report
