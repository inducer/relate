#! /bin/sh

USER=andreas
RELATE_GIT_ROOT=/home/andreas/work/django

for i in "$RELATE_GIT_ROOT"/*; do
  if test -d "$i/.git"; then
    su $USER -c "cd $i ; git repack -a -d"
  fi
done

