#! /bin/bash

# before_script
if [[ $RL_TRAVIS_TEST == flake8 ]]; then
  curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-flake8.sh
fi

if [[ $RL_TRAVIS_TEST == mypy ]]; then
  curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-mypy.sh
fi

# run ci according to env variables
if [[ $RL_TRAVIS_TEST == test* ]]; then
  . ./run-tests-for-ci.sh
elif [[ $RL_TRAVIS_TEST == cmdline ]]; then
  . ./test-command-line-tool.sh python3.6
elif [[ $RL_TRAVIS_TEST == mypy ]]; then
  . ./prepare-and-run-mypy.sh python3.6 mypy==0.560
elif [[ $RL_TRAVIS_TEST == flake8 ]]; then
  . ./prepare-and-run-flake8.sh relate course accounts tests bin
fi
