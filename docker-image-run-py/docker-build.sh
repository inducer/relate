#! /bin/sh
cp ../course/page/code_feedback.py .
cp ../course/page/code_run_backend_python.py code_run_backend.py
docker build --no-cache . -t inducer/relate-runcode-python
rm code_feedback.py code_run_backend.py
