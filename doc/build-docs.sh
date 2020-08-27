#! /bin/bash

set -e

# This whole script is being run inside of poetry, so no need to wrap move of
# it in poetry calls.

python -m pip install docutils sphinx

cp local_settings_example.py doc

cd doc

cat > doc_upload_ssh_config <<END
Host doc-upload
   User doc
   IdentityFile doc_upload_key
   IdentitiesOnly yes
   Hostname marten.tiker.net
   StrictHostKeyChecking false
END

make html SPHINXOPTS="-W --keep-going -n"

if test -n "${DOC_UPLOAD_KEY}"; then
  echo "${DOC_UPLOAD_KEY}" > doc_upload_key
  chmod 0600 doc_upload_key
  RSYNC_RSH="ssh -F doc_upload_ssh_config" ./upload-docs.sh || { rm doc_upload_key; exit 1; }
  rm doc_upload_key
else
  echo "Skipping upload. DOC_UPLOAD_KEY was not provided."
fi
