#! /bin/bash

set -eo pipefail

EXAM=0
if test "$1" == "--exam"; then
    echo "BUILDING IN EXAM MODE"
    EXAM=1
fi

MATHJAX_VER=2.7.7

rm -Rf env _output files pack
python -m venv env

source env/bin/activate

# jupyter-server appears to be needed for indexing contents
# update the pyodide kernel and pyodide below in lockstep
pip install jupyterlite-core 'jupyterlite-pyodide-kernel==0.1.2' jupyter-server libarchive-c

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

(cd pack; unzip mathjax-$MATHJAX_VER.zip)

jupyter lite init
jupyter lite build \
        --mathjax-dir "pack/MathJax-$MATHJAX_VER" \
        --pyodide https://github.com/pyodide/pyodide/releases/download/0.24.0/pyodide-0.24.0.tar.bz2
