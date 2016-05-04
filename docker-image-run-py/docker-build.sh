#! /bin/sh
cp ../course/page/code_feedback.py ../course/page/code_runpy_backend.py .
docker build .
rm code_feedback.py code_runpy_backend.py

