#! /bin/sh
cp ../course/page/code_feedback.py .
cp ../course/page/code_run_backend_octave.py .
docker build --no-cache . -t davis68/relate-runcode-octave
rm code_feedback.py code_run_backend_octave.py
