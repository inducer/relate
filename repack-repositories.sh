#! /bin/sh

USER=www-data
RELATE_GIT_ROOT=/web/relate-git-root

for i in "$RELATE_GIT_ROOT"/*; do
  if test -d "$i/.git"; then
    (cd $i; sudo -u $USER git repack -a -d)
  fi
done

