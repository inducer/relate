#! /bin/bash

set -eo pipefail

EXAM=0
if test "$1" == "--exam"; then
    echo "BUILDING IN EXAM MODE"
    EXAM=1
fi

MATHJAX_VER=2.7.7

./cleanup.sh

EXTRA_BUILD_FLAGS=()

if test "$EXAM" = 0; then
    python -m venv env

    source env/bin/activate
    pip install jupyterlite-core
    # update the pyodide kernel and pyodide in lockstep
    pip install 'jupyterlite-pyodide-kernel==0.1.2'

    EXTRA_BUILD_FLAGS=(--pyodide https://github.com/pyodide/pyodide/releases/download/0.24.0/pyodide-0.24.0.tar.bz2)
else
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj --strip=1 bin/micromamba
    ./micromamba create -y -f build-environment.yml -p ./mamba-root
    eval "$(./micromamba shell hook --shell bash)"
    micromamba activate ./mamba-root
fi

# jupyter-server appears to be needed for indexing contents
pip install jupyter-server libarchive-c

mkdir -p pack

if [[ "$EXAM" = 0 ]]; then
    mkdir -p files/{cs450,cs555}

    git clone https://github.com/inducer/numerics-notes pack/numerics-notes
    git clone https://github.com/inducer/numpde-notes pack/numpde-notes

    cp -R pack/numerics-notes/demos files/cs450/demos
    cp -R pack/numerics-notes/cleared-demos files/cs450/cleared
    cp -R pack/numpde-notes/demos files/cs555/demos
    cp -R pack/numpde-notes/cleared-demos files/cs555/cleared
fi

curl -L "https://github.com/mathjax/MathJax/archive/$MATHJAX_VER.zip" \
        -o "pack/mathjax-$MATHJAX_VER.zip"

(cd pack; unzip --quiet mathjax-$MATHJAX_VER.zip)

jupyter lite init
jupyter lite build \
        --mathjax-dir "pack/MathJax-$MATHJAX_VER" \
        "${EXTRA_BUILD_FLAGS[@]}"

# vim: sw=4
