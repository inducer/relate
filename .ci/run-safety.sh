#! /bin/bash
# 38678: django-celery-results: no update currently available
# https://github.com/celery/django-celery-results/issues/154
poetry run safety check \
        -i 38678 \
        --full-report
