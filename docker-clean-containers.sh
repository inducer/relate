#! /bin/bash
docker rm $(docker ps -a | cut -d ' ' -f1 | tail -n +2)
