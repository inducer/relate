#! /bin/bash

if test -d files/cs450-kloeckner; then
    echo "Uploading in normal mode..."
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/main/
else
    echo "Uploading in exam mode..."
    rsync --archive --delete -v _output/ rl:/web/jupyterlite/exam/
fi
