#! /bin/bash

set -eo pipefail

uv sync --all-extras --all-groups --no-group mypy --frozen
npm install
npm run build
./collectstatic.sh
