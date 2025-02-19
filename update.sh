#! /bin/bash

set -eo pipefail

uv sync --all-extras --frozen
npm install
npm run build
./collectstatic.sh
