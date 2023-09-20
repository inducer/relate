#! /bin/bash

if test -d files/cs450; then
    rsync --archive --delete -v _output/ rl:jupyterlite/
else
    rsync --archive --delete -v _output/ rl:jupyterlite-exam/
fi
