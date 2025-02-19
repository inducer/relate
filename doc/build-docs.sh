#! /bin/bash

set -e

# This whole script is being run inside of uv, so no need to wrap move of
# it in uv calls.

cp local_settings_example.py doc

cd doc

cat > doc_upload_ssh_config <<END
Host doc-upload
   User doc
   IdentityFile doc_upload_key
   IdentitiesOnly yes
   Hostname documen.tician.de
   StrictHostKeyChecking false
   Port 2222
END

make html SPHINXOPTS="-W --keep-going -n"

if test -n "${DOC_UPLOAD_KEY}" && test "$CI_COMMIT_REF_NAME" = "main"; then
  echo "${DOC_UPLOAD_KEY}" > doc_upload_key
  chmod 0600 doc_upload_key
  RSYNC_RSH="ssh -F doc_upload_ssh_config" ./upload-docs.sh || { rm doc_upload_key; exit 1; }
  rm doc_upload_key
else
  echo "Skipping upload. DOC_UPLOAD_KEY was not provided."
fi
