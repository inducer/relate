#! /bin/bash

set -eo pipefail

MATHJAX_VER=2.7.7

rm -Rf env _output files pack
python -m venv env

source env/bin/activate

# jupyter-server appears to be needed for indexing contents
pip install jupyterlite-core jupyterlite-pyodide-kernel jupyter-server libarchive-c

mkdir -p pack
mkdir -p files/{cs450,cs555}

git clone https://github.com/inducer/numerics-notes pack/numerics-notes
git clone https://github.com/inducer/numpde-notes pack/numpde-notes

cp -R pack/numerics-notes/demos files/cs450/demos
cp -R pack/numerics-notes/cleared-demos files/cs450/cleared
cp -R pack/numpde-notes/demos files/cs555/demos
cp -R pack/numpde-notes/cleared-demos files/cs555/cleared

curl -L "https://github.com/mathjax/MathJax/archive/$MATHJAX_VER.zip" \
        -o "pack/mathjax-$MATHJAX_VER.zip"

(cd pack; unzip mathjax-$MATHJAX_VER.zip)

jupyter lite init
jupyter lite build \
        --mathjax-dir "pack/MathJax-$MATHJAX_VER" \
        --pyodide https://github.com/pyodide/pyodide/releases/download/0.22.1/pyodide-0.22.1.tar.bz2
