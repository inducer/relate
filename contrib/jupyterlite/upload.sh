#! /bin/bash
rsync --archive --delete -v _output/ rl:jupyterlite/
