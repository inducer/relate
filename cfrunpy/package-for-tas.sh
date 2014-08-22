#! /bin/bash

set -e

mkdir autograde
cp cfrunpy_backend.py autograde
cp demo*.{yml,py} autograde
cp simulate-test.py autograde
cp -R ~/pack/PyYAML-3.11/lib3/yaml autograde

tar cfz autograde-sim.tar.gz autograde

rm -Rf autograde
