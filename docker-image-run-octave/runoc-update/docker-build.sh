#! /bin/sh
cp ../../course/page/code_feedback.py .
cp ../../course/page/code_runoc_backend.py code_run_backend.py
docker build --no-cache . -t inducer/runoc-update
rm code_feedback.py code_run_backend.py
