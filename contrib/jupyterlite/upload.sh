#! /bin/bash

if test -d files/cs450; then
    echo "UPLOADING FOR DEFAULT MODE"
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/main/
else
    echo "UPLOADING FOR EXAM MODE"
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/exam/
fi
