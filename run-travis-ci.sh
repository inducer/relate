#! /bin/bash

export RL_CI_TEST="$RL_TRAVIS_TEST"

# before_script
# if [[ $RL_TRAVIS_TEST == flake8 ]]; then
#   curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-flake8.sh
# fi

# if [[ $RL_TRAVIS_TEST == mypy ]]; then
#   curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-mypy.sh
# fi

# run ci according to env variables
if [[ $RL_TRAVIS_TEST == test* ]]; then
  . ./run-tests-for-ci.sh
elif [[ $RL_TRAVIS_TEST == cmdline ]]; then
  . ./test-command-line-tool.sh $PY_EXE
elif [[ $RL_TRAVIS_TEST == mypy ]]; then
  # . ./prepare-and-run-mypy.sh $PY_EXE mypy==0.641
  poetry run mypy relate course
elif [[ $RL_TRAVIS_TEST == flake8 ]]; then
  poetry run flake8 relate course accounts tests
  # . ./prepare-and-run-flake8.sh relate course accounts tests bin
fi
