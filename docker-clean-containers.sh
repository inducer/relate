#! /bin/bash
docker rm -f $(docker ps -a | cut -d ' ' -f1 | tail -n +2)
