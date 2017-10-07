#! /bin/bash

# before_script
if [[ $Flake8 == true ]]; then
  curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-flake8.sh
fi

if [[ $Mypy == true ]]; then
  curl -L -O -k https://gitlab.tiker.net/inducer/ci-support/raw/master/prepare-and-run-mypy.sh
fi

if [[ $PY == true ]]; then

  # We are not using tls verify, skipping the cert bother. To disable tls verify,
  # DOCKER_TLS_VERIFY should be an empty string (0 or false won't work).
  # Ref https://github.com/moby/moby/issues/22339
  export DOCKER_TLS_VERIFY=

  # Controller for real docker unittest
  export ENABLE_DOCKER_TEST=True

  # load cached docker image: https://github.com/travis-ci/travis-ci/issues/5358#issuecomment-248915326
  if [[ -d $HOME/docker ]]; then
    ls $HOME/docker/*.tar.gz | xargs -I {file} sh -c "zcat {file} | docker load"
    if [[ "$(docker images -q inducer/relate-runpy-i386:latest 2> /dev/null)" == "" ]]; then
      docker pull inducer/relate-runpy-i386
    fi
  fi
fi

# run ci according to env variables
if [[ $PY == true ]]; then
  . ./run-tests-for-ci.sh
elif [[ $Mypy == true ]]; then
  . ./prepare-and-run-mypy.sh python3.6 mypy==0.521 typed-ast==1.0.4
elif [[ $Flake8 == true ]]; then
  . ./prepare-and-run-flake8.sh relate course accounts tests bin
fi