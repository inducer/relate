#! /bin/bash

set -eo pipefail

poetry install -E postgres -E memcache
npm install
npm run build
./collectstatic.sh
