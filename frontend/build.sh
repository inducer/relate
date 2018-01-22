#! /bin/bash

set -e
set -x

mathjax_version="2.7.2"
mathjax_want_sha256="03163db51af354738871c4e123a11d3f4a0b58f2460c347a55101923cc6a082b"
mathjax_fn="mathjax-$mathjax_version.zip"

mathjax_need_dl=1
if [[ -f "$mathjax_fn" ]]; then
  mathjax_sha256=$(sha256sum "$mathjax_fn" | cut -d' ' -f1)
  if test "$mathjax_sha256" == "$mathjax_want_sha256"; then
    mathjax_need_dl=0
  fi
fi

if [[ "$mathjax_need_dl" != "0" ]]; then
  curl -L -o "$mathjax_fn" "https://github.com/mathjax/MathJax/archive/$mathjax_version.zip"
fi

yarn install
./node_modules/.bin/webpack

if test "$mathjax_fn" -nt "dist/mathjax"; then
  rm -Rf dist/mathjax
  (cd dist && unzip ../$mathjax_fn && mv MathJax-$mathjax_version mathjax && touch mathjax)
fi
