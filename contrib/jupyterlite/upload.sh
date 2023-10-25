#! /bin/bash

if test -d files/cs450; then
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/main/
else
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/exam/
fi
