#! /bin/sh

if test "$1" = "-f"; then
        RLCONTAINER=full
        IMGNAME=inducer/relate-runcode-python-amd64-full
else
        RLCONTAINER=base
        IMGNAME=inducer/relate-runcode-python-amd64
fi

cp ../course/page/code_feedback.py .
cp ../course/page/code_run_backend.py .

docker build --no-cache --build-arg RLCONTAINER="$RLCONTAINER" . -t $IMGNAME
rm code_feedback.py code_run_backend.py
