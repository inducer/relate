#! /bin/bash

find node_modules/mathjax/es5 -name '*.js' -exec sed -i /sourceMappingURL=/d '{}' \;
poetry run python manage.py collectstatic
