#! /bin/sh
cp ../../course/page/code_feedback.py ../../course/page/code_runoc_backend.py .
docker build --no-cache . -t inducer/runoc-update
rm code_feedback.py code_runoc_backend.py
