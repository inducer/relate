#! /bin/sh
cp ../course/page/code_feedback.py .
cp ../course/page/code_run_backend_py.py ./code_run_backend.py
docker build --no-cache . -t inducer/relate-runpy-amd64
rm code_feedback.py code_run_backend.py
