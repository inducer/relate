#! /bin/bash

if test "$1" = ""; then 
  echo "$0 imagename"
  exit 1
fi
CONTAINER=$(docker create "$1")
docker export "$CONTAINER" | \
  docker import \
    -c "EXPOSE 9941" \
    -
docker rm -f $CONTAINER
